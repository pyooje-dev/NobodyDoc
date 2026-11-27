"""Code source, requêtes SQL et fichiers de configuration.

Le fichier est traité comme un texte unique, sans rien changer d'autre que les
valeurs sensibles : indentation, fins de ligne et encodage sont conservés, et
les jetons (« [EMAIL_1] ») restent à l'intérieur des guillemets d'origine, ce
qui garde le code valide.

Les règles (e-mails, URL, IP, serveurs, secrets...) et le dictionnaire lisent
tout le fichier. Le modèle de langue, lui, ne lit que les commentaires et les
chaînes de caractères : sur le code lui-même, il prendrait des noms de variables
ou de tables pour des noms de personnes.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..entities import CodeText, ProseText
from ..session import AnonymizationSession
from .base import FileReport
from .text import decode

# Familles de syntaxe : comment repérer commentaires et chaînes.
_FAMILIES = {
    "sql": (".sql",),
    "c": (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".kts", ".scala",
          ".groovy", ".cs", ".c", ".h", ".cpp", ".hpp", ".go", ".rs", ".swift", ".php",
          ".dart"),
    "hash": (".py", ".rb", ".r", ".pl", ".sh", ".bash", ".zsh", ".ps1", ".psm1"),
    "batch": (".bat", ".cmd", ".vbs"),
    "kv": (".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties"),
    "xml": (".xml", ".config", ".xaml", ".html", ".htm"),
}
_FAMILY_OF = {ext: family for family, exts in _FAMILIES.items() for ext in exts}

_STRINGS = r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
_TOKENIZERS = {
    # En SQL, "..." désigne une colonne ou une table : seules les chaînes '...' comptent.
    "sql": re.compile(r"--[^\n]*|/\*[\s\S]*?\*/|'(?:[^']|'')*'"),
    "c": re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|#(?=\s)[^\n]*|`(?:[^`\\]|\\.)*`|" + _STRINGS),
    "hash": re.compile(r"(?:(?<=\s)|^)#[^\n]*|<#[\s\S]*?#>|" + _STRINGS, re.M),
    "batch": re.compile(r"(?:^|(?<=\s))(?:REM\b|::|')[^\n]*|\"[^\"\n]*\"", re.M | re.I),
}
_KV_LINE = re.compile(r"^\s*(?:[#;!]\s*(?P<comment>.*)|[^=:#;\n]+[=:]\s*(?P<value>.*))$", re.M)
_XML_PARTS = re.compile(r"<!--([\s\S]*?)-->|=\s*\"([^\"]*)\"|=\s*'([^']*)'|>([^<]+)<")


def prose_fragments(text: str, family: str) -> list[str]:
    """Commentaires et contenus de chaînes, sans les délimiteurs."""
    fragments: list[str] = []
    if family == "kv":
        for m in _KV_LINE.finditer(text):
            fragments.append((m.group("comment") or m.group("value") or "").strip().strip("\"'"))
    elif family == "xml":
        for m in _XML_PARTS.finditer(text):
            fragments.append(next(g for g in m.groups() if g is not None))
    else:
        for m in _TOKENIZERS[family].finditer(text):
            token = m.group()
            token = re.sub(r"^(?:--|//|/\*|<#|#|REM\b|::|\"\"\"|'''|[\"'`])", "", token, flags=re.I)
            token = re.sub(r"(?:\*/|#>|\"\"\"|'''|[\"'`])$", "", token)
            fragments.append(token)
    # Le modèle de langue n'a besoin que de phrases : pas d'une valeur isolée
    # (« north ») ni d'une chaîne technique (« Server=...;User ID=... »).
    return [f.strip() for f in fragments if _is_prose(f.strip())]


def _is_prose(fragment: str) -> bool:
    if not re.search(r"[^\W\d_]{2,}\s+[^\W\d_]{2,}", fragment):
        return False
    return not re.search(r"[\w\]]\s*=|;\s*\w+\s*=|\b(?:select|insert|update|delete)\b.+\b(?:from|into|set|where)\b",
                         fragment, re.I)


class CodeHandler:
    extensions = tuple(_FAMILY_OF)

    def __init__(self, family: str):
        self.family = family

    @classmethod
    def for_extension(cls, ext: str) -> "CodeHandler | None":
        family = _FAMILY_OF.get(ext.lower())
        return _HANDLERS[family] if family else None

    def iter_texts(self, data: bytes) -> Iterator[str]:
        text, _ = decode(data)
        yield CodeText(text)
        for fragment in prose_fragments(text, self.family):
            yield ProseText(fragment)

    def anonymize(self, data: bytes, session: AnonymizationSession, report: FileReport) -> bytes:
        text, encoding = decode(data)
        result = session.apply(text)
        report.count(result.replacements)
        return result.text.encode(encoding, errors="replace")


_HANDLERS = {family: CodeHandler(family) for family in _FAMILIES}
