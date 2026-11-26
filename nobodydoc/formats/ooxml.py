"""Word (.docx), Excel (.xlsx) et PowerPoint (.pptx).

Ces formats sont des archives ZIP de fichiers XML. On modifie directement le
texte dans le XML, ce qui conserve toute la mise en forme (styles, tableaux,
images, graphiques). Un même paragraphe est souvent découpé en plusieurs
« runs » (morceaux de texte avec leur propre mise en forme) : le texte est
d'abord recollé pour la détection, puis redistribué dans les runs d'origine.

Sont traités : corps du texte, tableaux, en-têtes et pieds de page, notes,
commentaires et leurs auteurs, révisions (texte supprimé compris), zones de
texte, codes de champ, graphiques, notes du présentateur, liens hypertexte,
propriétés du document (auteur, société...) et documents Office incorporés.
La miniature d'aperçu est supprimée.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

from lxml import etree

from ..session import AnonymizationSession
from .base import FileReport

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# (élément paragraphe, élément texte) : le texte est recollé par paragraphe.
TEXT_GROUPS = [
    (f"{{{W}}}p", f"{{{W}}}t"),
    (f"{{{W}}}p", f"{{{W}}}delText"),
    (f"{{{W}}}p", f"{{{W}}}instrText"),
    (f"{{{A}}}p", f"{{{A}}}t"),
    (f"{{{X}}}si", f"{{{X}}}t"),  # chaînes partagées Excel
    (f"{{{X}}}is", f"{{{X}}}t"),  # chaînes en ligne Excel
    (f"{{{X}}}text", f"{{{X}}}t"),  # commentaires Excel
    (f"{{{C}}}pt", f"{{{C}}}v"),  # libellés des graphiques
    (f"{{{C}}}tx", f"{{{C}}}v"),  # noms de séries
]

# Attributs contenant le nom d'une personne (auteurs de commentaires, révisions).
PERSON_ATTRIBUTES = {"author", "displayName"}
PERSON_ELEMENTS_NAME_ATTR = {"cmAuthor", "author", "person"}
ERASE_ATTRIBUTES = {"initials", "userId", "providerId"}

# Propriétés vidées sans analyse (auteur, dernier modificateur, société...).
BLANKED_PROPERTIES = {"creator", "lastModifiedBy", "Company", "Manager", "HyperlinkBase"}

EMBEDDED_OFFICE = (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm")
SKIP_PARTS = re.compile(r"(^|/)(theme\d*|fontTable|webSettings|styles|stylesWithEffects|"
                        r"numbering|settings|presProps|viewProps|tableStyles|calcChain|"
                        r"vbaData)\.xml$")
THUMBNAIL = re.compile(r"^docProps/thumbnail\.\w+$")
IMAGE_PART = re.compile(r"\.(png|jpe?g|gif|bmp|tiff?|emf|wmf|svg)$", re.I)


@dataclass
class _Part:
    name: str
    data: bytes


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _parse(data: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, remove_blank_text=False)
    return etree.fromstring(data, parser)


def _serialize(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _nearest(elem, tag):
    parent = elem.getparent()
    while parent is not None and parent.tag != tag:
        parent = parent.getparent()
    return parent


def _text_groups(root) -> Iterator[list]:
    """Pour chaque paragraphe, la liste ordonnée de ses éléments texte."""
    for para_tag, text_tag in TEXT_GROUPS:
        groups: dict = {}
        order = []
        for t in root.iter(text_tag):
            para = _nearest(t, para_tag)
            key = para if para is not None else t
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(t)
        for key in order:
            yield groups[key]


def redistribute(segments: list[str], replacements: list[tuple[int, int, str]]) -> list[str]:
    """Applique des remplacements sur le texte recollé, en le rendant à ses runs.

    Le texte de remplacement est placé dans le run où commence la valeur
    d'origine ; les caractères remplacés sont retirés des runs suivants.
    """
    owners = []
    for i, seg in enumerate(segments):
        owners.extend([i] * len(seg))
    full = "".join(segments)
    out = [""] * len(segments)
    pos = 0
    for start, end, new in sorted(replacements):
        for k in range(pos, start):
            out[owners[k]] += full[k]
        if start < len(owners):
            out[owners[start]] += new
        elif segments:
            out[-1] += new
        pos = end
    for k in range(pos, len(full)):
        out[owners[k]] += full[k]
    return out


class OoxmlHandler:
    extensions = (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm")

    # -------------------------------------------------------------- passe 1

    def iter_texts(self, data: bytes) -> Iterator[str]:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                name = info.filename
                if name.lower().endswith(EMBEDDED_OFFICE):
                    yield from self.iter_texts(zf.read(info))
                    continue
                if not self._is_text_part(name):
                    continue
                root = _parse(zf.read(info))
                for group in _text_groups(root):
                    text = "".join(t.text or "" for t in group)
                    if text.strip():
                        yield text
                if name.startswith("docProps/"):
                    for el in root.iter():
                        if (isinstance(el.tag, str) and el.text and el.text.strip() and len(el) == 0
                                and _local(el.tag) not in BLANKED_PROPERTIES):
                            yield el.text

    # -------------------------------------------------------------- passe 2

    def anonymize(self, data: bytes, session: AnonymizationSession, report: FileReport) -> bytes:
        src = zipfile.ZipFile(io.BytesIO(data))
        out_buf = io.BytesIO()
        removed: set[str] = set()
        with src, zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                name = info.filename
                content = src.read(info)
                if THUMBNAIL.match(name):
                    removed.add(name)
                    report.warn("Miniature d'aperçu supprimée.")
                    continue
                if name.lower().endswith(EMBEDDED_OFFICE):
                    content = self.anonymize(content, session, report)
                elif name.endswith(".rels"):
                    content = self._fix_rels(content, session, report)
                elif self._is_text_part(name):
                    content = self._anonymize_part(name, content, session, report)
                elif IMAGE_PART.search(name):
                    report.images += 1
                elif name.lower().endswith(".bin") and "embeddings" in name:
                    report.warn(f"Objet incorporé non analysé : {name.rsplit('/', 1)[-1]}")
                new_info = zipfile.ZipInfo(name, date_time=info.date_time)
                new_info.compress_type = zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                dst.writestr(new_info, content)
        if removed:
            return self._drop_relationships(out_buf.getvalue(), removed)
        return out_buf.getvalue()

    # -------------------------------------------------------------- détails

    @staticmethod
    def _is_text_part(name: str) -> bool:
        return name.endswith(".xml") and not SKIP_PARTS.search(name) and name != "[Content_Types].xml"

    def _anonymize_part(self, name: str, content: bytes, session, report: FileReport) -> bytes:
        root = _parse(content)
        changed = False

        for group in _text_groups(root):
            segments = [t.text or "" for t in group]
            result = session.apply("".join(segments))
            if not result.changed:
                continue
            report.count(result.replacements)
            new_segments = redistribute(
                segments, [(r.span.start, r.span.end, r.placeholder) for r in result.replacements]
            )
            for t, new in zip(group, new_segments):
                if t.text != new:
                    t.text = new
                    if t.tag.startswith(f"{{{W}}}") or t.tag.startswith(f"{{{X}}}"):
                        t.set(XML_SPACE, "preserve")
            changed = True

        changed |= self._anonymize_people(root, session, report)

        if name.startswith("docProps/"):
            changed |= self._anonymize_properties(name, root, session, report)

        if name.endswith("workbook.xml"):
            for sheet in root.iter(f"{{{X}}}sheet"):
                if session.apply(sheet.get("name", "")).changed:
                    report.warn(
                        f"Le nom d'onglet « {sheet.get('name')} » contient une donnée sensible : "
                        "renommez-le à la main (il peut être utilisé dans des formules)."
                    )
        return _serialize(root) if changed else content

    @staticmethod
    def _anonymize_people(root, session, report: FileReport) -> bool:
        changed = False
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            local = _local(el.tag)
            for attr in list(el.attrib):
                attr_local = _local(attr)
                value = el.get(attr)
                if attr_local in PERSON_ATTRIBUTES or (
                    attr_local == "name" and local in PERSON_ELEMENTS_NAME_ATTR
                ):
                    new = session.pseudonymize_value(value, "PERSONNE")
                elif attr_local in ERASE_ATTRIBUTES and local in PERSON_ELEMENTS_NAME_ATTR | {
                    "comment", "presenceInfo"
                }:
                    new = ""
                else:
                    continue
                if new != value:
                    el.set(attr, new)
                    report.metadata += 1
                    changed = True
            # <authors><author>Jean Dupont</author></authors> des commentaires Excel
            if local == "author" and el.text and el.text.strip() and len(el) == 0:
                new = session.pseudonymize_value(el.text, "PERSONNE")
                if new != el.text:
                    el.text = new
                    report.metadata += 1
                    changed = True
        return changed

    @staticmethod
    def _anonymize_properties(name: str, root, session, report: FileReport) -> bool:
        changed = False
        for el in root.iter():
            if not isinstance(el.tag, str) or len(el) or not el.text or not el.text.strip():
                continue
            local = _local(el.tag)
            if local in BLANKED_PROPERTIES:
                el.text = ""
                report.metadata += 1
                changed = True
            elif local not in ("created", "modified", "Template", "Application", "AppVersion",
                               "TotalTime", "Pages", "Words", "Characters", "Lines",
                               "Paragraphs", "Slides", "Notes", "DocSecurity", "revision"):
                result = session.apply(el.text)
                if result.changed:
                    el.text = result.text
                    report.count(result.replacements)
                    changed = True
        return changed

    @staticmethod
    def _fix_rels(content: bytes, session, report: FileReport) -> bytes:
        root = _parse(content)
        changed = False
        for rel in root.iter(f"{{{REL}}}Relationship"):
            if rel.get("TargetMode") != "External":
                continue
            target = rel.get("Target", "")
            result = session.apply(target)
            if result.changed:
                rel.set("Target", quote(result.text, safe=":/?#=&@%+-_.~"))
                report.count(result.replacements)
                changed = True
        return _serialize(root) if changed else content

    @staticmethod
    def _drop_relationships(data: bytes, removed: set[str]) -> bytes:
        src = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                content = src.read(info)
                if info.filename == "_rels/.rels":
                    root = _parse(content)
                    for rel in list(root.iter(f"{{{REL}}}Relationship")):
                        if rel.get("Target", "").lstrip("/") in removed:
                            root.remove(rel)
                    content = _serialize(root)
                dst.writestr(info, content)
        return out.getvalue()

