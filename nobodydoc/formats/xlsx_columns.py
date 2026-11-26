"""Excel : repère les colonnes de noms grâce à leur en-tête.

Dans un tableau, une cellule « DUPONT Jean » n'a pas de contexte : le modèle
de langue ne la reconnaît pas toujours, ou n'en reconnaît qu'une partie. Si
l'en-tête de la colonne indique qu'elle contient des personnes (« NOM Prénom »,
« Contact », « Salarié »...) ou des sociétés (« Client », « Raison sociale »...),
chaque cellule de la colonne est masquée en entier.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Iterator

from lxml import etree

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

PERSON_HEADER = re.compile(
    r"\b(nom|noms|pr[ée]nom|pr[ée]noms|name|names|first ?name|last ?name|surname|full ?name|"
    r"contact|salari[ée]e?s?|collaborat(eur|rice)s?|employ[ée]e?s?|agent|interlocut(eur|rice)|"
    r"responsable|manager|destinataire|exp[ée]diteur|auteur|signataire|titulaire|"
    r"b[ée]n[ée]ficiaire|demandeur|patient|candidat|[ée]l[èe]ve|stagiaire|personne|intervenant|"
    r"r[ée]f[ée]rent|chef de projet|commercial|conseiller|propri[ée]taire|locataire|"
    r"nom (de )?(famille|naissance|usage))\b",
    re.IGNORECASE,
)
ORG_HEADER = re.compile(
    r"\b(soci[ée]t[ée]|entreprise|raison sociale|client|clients|fournisseur|fournisseurs|"
    r"organisme|employeur|company|customer|supplier|partenaire|prestataire|enseigne|"
    r"[ée]tablissement|banque|cabinet|agence)\b",
    re.IGNORECASE,
)
# En-têtes qui contiennent « nom » mais ne désignent pas une personne.
NOT_PERSON = re.compile(
    r"\b(produit|projet|fichier|document|service|d[ée]partement|rue|voie|ville|commune|"
    r"domaine|onglet|feuille|colonne|champ|article|r[ée]f[ée]rence|mod[èe]le|code|"
    r"e-?mail|mail|t[ée]l[ée]phone|adresse|date|id|identifiant|nombre)\b",
    re.IGNORECASE,
)


def header_category(header: str) -> str | None:
    header = header.strip()
    if not header or len(header) > 60:
        return None
    if NOT_PERSON.search(header):
        return None
    if ORG_HEADER.search(header) and not re.search(r"\b(nom|pr[ée]nom|contact)\b", header, re.I):
        return "ORGANISATION"
    if PERSON_HEADER.search(header):
        return "PERSONNE"
    if ORG_HEADER.search(header):
        return "ORGANISATION"
    return None


def _col(ref: str) -> str:
    return re.sub(r"\d", "", ref or "")


def _row(ref: str) -> int:
    digits = re.sub(r"\D", "", ref or "")
    return int(digits) if digits else 0


def _plausible(value: str) -> bool:
    value = value.strip()
    if len(value) < 2 or len(value) > 80 or "@" in value or "\n" in value:
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", value):
        return False
    if re.fullmatch(r"[\d\s.,/:%€$-]+", value):
        return False
    return len(value.split()) <= 6


def iter_column_entities(data: bytes) -> Iterator[tuple[str, str]]:
    """(valeur, catégorie) pour chaque cellule d'une colonne de noms ou de sociétés."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = etree.fromstring(zf.read("xl/sharedStrings.xml"), etree.XMLParser(resolve_entities=False, huge_tree=True))
            for si in root.iter(f"{{{X}}}si"):
                # Le texte phonétique (rPh) n'est pas affiché : on l'ignore.
                shared.append("".join(t.text or "" for t in si.iter(f"{{{X}}}t")
                                      if t.getparent().tag != f"{{{X}}}rPh"))
        for name in names:
            if not re.match(r"^xl/worksheets/sheet\d+\.xml$", name):
                continue
            root = etree.fromstring(zf.read(name), etree.XMLParser(resolve_entities=False, huge_tree=True))
            rows: dict[int, dict[str, str]] = {}
            for cell in root.iter(f"{{{X}}}c"):
                kind = cell.get("t")
                text = None
                if kind == "s":
                    v = cell.find(f"{{{X}}}v")
                    if v is not None and v.text and v.text.strip().isdigit() and int(v.text) < len(shared):
                        text = shared[int(v.text)]
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(f"{{{X}}}t"))
                elif kind == "str":
                    v = cell.find(f"{{{X}}}v")
                    text = v.text if v is not None else None
                if text and text.strip():
                    ref = cell.get("r", "")
                    rows.setdefault(_row(ref), {})[_col(ref)] = text.strip()
            if not rows:
                continue
            # La ligne d'en-tête : la première ligne (parmi les 10 premières) qui
            # contient au moins un en-tête de nom reconnu.
            header_row, columns = None, {}
            for row_number in sorted(rows)[:10]:
                found = {col: cat for col, value in rows[row_number].items() if (cat := header_category(value))}
                if found:
                    header_row, columns = row_number, found
                    break
            if header_row is None:
                continue
            for row_number in sorted(rows):
                if row_number <= header_row:
                    continue
                for col, category in columns.items():
                    value = rows[row_number].get(col)
                    if value and _plausible(value):
                        yield value, category
