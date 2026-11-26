"""Dictionnaire de l'entreprise : termes à toujours masquer et termes à ne jamais masquer.

Formats acceptés :

* JSON ::

    {
      "termes": [
        {"terme": "Acme", "categorie": "CLIENT", "variantes": ["ACME Corp"]},
        {"terme": "DSI", "categorie": "DEPARTEMENT"}
      ],
      "exclusions": ["Microsoft", "Excel"]
    }

* CSV (séparateur « ; », éditable dans Excel) ::

    terme;categorie;variantes
    Acme;CLIENT;ACME Corp|Acme SAS
    DSI;DEPARTEMENT;
    Microsoft;EXCLUSION;
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .entities import Span, normalize_category, normalize_value


@dataclass
class DictionaryTerm:
    term: str
    category: str
    variants: list[str] = field(default_factory=list)

    @property
    def all_forms(self) -> list[str]:
        return [f for f in [self.term, *self.variants] if f and f.strip()]


def is_acronym(form: str) -> bool:
    """Un acronyme en majuscules (DSI, RH, PX-200) est cherché en respectant la casse."""
    letters = [c for c in form if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and len(form) <= 12


class CompanyDictionary:
    def __init__(self, terms: list[DictionaryTerm] | None = None, exclusions: list[str] | None = None):
        self.terms: list[DictionaryTerm] = list(terms or [])
        self.exclusions: set[str] = {normalize_value("", e) for e in (exclusions or []) if e.strip()}
        self._compiled: list[tuple[re.Pattern, dict[str, str]]] | None = None

    # -- Chargement / sauvegarde ---------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "CompanyDictionary":
        path = Path(path)
        raw = path.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError(f"Encodage illisible : {path}")
        if path.suffix.lower() == ".json":
            return cls.from_json(text)
        return cls.from_csv(text)

    @classmethod
    def from_json(cls, text: str) -> "CompanyDictionary":
        data = json.loads(text)
        terms = [
            DictionaryTerm(
                term=str(item.get("terme", "")).strip(),
                category=normalize_category(str(item.get("categorie", "DIVERS"))),
                variants=[str(v).strip() for v in item.get("variantes", []) if str(v).strip()],
            )
            for item in data.get("termes", [])
            if str(item.get("terme", "")).strip()
        ]
        return cls(terms, data.get("exclusions", []))

    @classmethod
    def from_csv(cls, text: str) -> "CompanyDictionary":
        sample = text[:2048]
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        terms, exclusions = [], []
        for i, row in enumerate(reader):
            if not row or not row[0].strip():
                continue
            if i == 0 and row[0].strip().lower() in ("terme", "term"):
                continue
            term = row[0].strip()
            category = normalize_category(row[1]) if len(row) > 1 and row[1].strip() else "DIVERS"
            variants = [v.strip() for v in row[2].split("|")] if len(row) > 2 else []
            if category in ("EXCLUSION", "EXCLURE", "NE_PAS_MASQUER"):
                exclusions.append(term)
            else:
                terms.append(DictionaryTerm(term, category, [v for v in variants if v]))
        return cls(terms, exclusions)

    def to_json(self) -> str:
        return json.dumps(
            {
                "termes": [
                    {"terme": t.term, "categorie": t.category, "variantes": t.variants}
                    for t in self.terms
                ],
                "exclusions": sorted(self.exclusions),
            },
            ensure_ascii=False,
            indent=2,
        )

    # -- Utilisation ----------------------------------------------------------

    def is_excluded(self, value: str) -> bool:
        return normalize_value("", value) in self.exclusions

    def category_for(self, value: str) -> str | None:
        key = normalize_value("", value)
        for term in self.terms:
            if any(normalize_value("", f) == key for f in term.all_forms):
                return term.category
        return None

    def canonical_for(self, value: str) -> str | None:
        """Forme principale d'un terme : toutes ses variantes partagent un même jeton."""
        key = normalize_value("", value)
        for term in self.terms:
            if any(normalize_value("", f) == key for f in term.all_forms):
                return term.term
        return None

    def _patterns(self) -> list[tuple[re.Pattern, dict[str, str]]]:
        if self._compiled is None:
            sensitive: dict[str, str] = {}
            insensitive: dict[str, str] = {}
            for term in self.terms:
                for form in term.all_forms:
                    if is_acronym(form):
                        sensitive[form] = term.category
                    else:
                        insensitive[normalize_value("", form)] = term.category
                        insensitive.setdefault(form.casefold(), term.category)
            compiled = []
            for forms, flags in ((sensitive, 0), (insensitive, re.IGNORECASE)):
                if forms:
                    alternatives = "|".join(
                        re.escape(f).replace(r"\ ", r"\s+")
                        for f in sorted(forms, key=len, reverse=True)
                    )
                    compiled.append((re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", flags), forms))
            self._compiled = compiled
        return self._compiled

    def find_spans(self, text: str) -> list[Span]:
        spans = []
        for pattern, _forms in self._patterns():
            for m in pattern.finditer(text):
                category = self.category_for(m.group()) or "DIVERS"
                spans.append(Span(m.start(), m.end(), category, "dictionnaire", m.group()))
        return spans
