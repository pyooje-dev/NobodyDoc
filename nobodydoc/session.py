"""Session d'anonymisation : détection, jetons cohérents et remplacement.

Le traitement se fait en deux passes sur l'ensemble des fichiers :

1. ``collect`` lit tous les textes et construit la liste des entités sensibles
   (c'est cette liste que l'interface montre pour validation) ;
2. ``apply`` remplace chaque occurrence par son jeton, par exemple
   « Jean Dupont » -> « [PERSONNE_1] », de façon identique dans tous les fichiers.

Comme la seconde passe recherche aussi toutes les valeurs déjà connues, un nom
repéré une seule fois par le modèle est masqué partout où il apparaît.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .detectors.ner import COMMON_FALSE_POSITIVES, NerDetector
from .detectors.rules import ALL_RULE_CATEGORIES, find_rule_spans
from .dictionary import CompanyDictionary, is_acronym
from .entities import (
    CASE_SENSITIVE_CATEGORIES,
    PLACEHOLDER_RE,
    CodeText,
    ProseText,
    SOURCE_PRIORITY,
    Entity,
    Span,
    normalize_category,
    normalize_value,
)


@dataclass
class SessionConfig:
    rule_categories: tuple[str, ...] = ALL_RULE_CATEGORIES
    use_ner: bool = True
    ner_labels: tuple[str, ...] = ("PER", "ORG")
    ner_model: str | None = None
    # « Jean Dupont » détecté => « Dupont » seul est aussi masqué.
    split_person_names: bool = True


@dataclass
class Replacement:
    span: Span
    placeholder: str


@dataclass
class ApplyResult:
    text: str
    replacements: list[Replacement] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.replacements)


class AnonymizationSession:
    def __init__(
        self,
        config: SessionConfig | None = None,
        dictionary: CompanyDictionary | None = None,
        ner: NerDetector | None = None,
    ):
        self.config = config or SessionConfig()
        self.dictionary = dictionary or CompanyDictionary()
        if ner is not None:
            self.ner = ner
        elif self.config.use_ner:
            self.ner = NerDetector(self.config.ner_model, self.config.ner_labels)
        else:
            self.ner = None
        self.entities: dict[str, Entity] = {}  # jeton -> entité
        self._index: dict[str, str] = {}  # clé normalisée -> jeton
        self._aliases: dict[str, set[str]] = {}  # jeton -> formes courtes (nom de famille...)
        self._counters: Counter[str] = Counter()
        self._known_re: list[re.Pattern] | None = None
        self._seen_texts: set[str] = set()
        self._seen_prose: set[str] = set()

    # ------------------------------------------------------------------ passe 1

    def collect(self, texts: Iterable[str]) -> None:
        batch = []
        for text in texts:
            if not text or not text.strip():
                continue
            if isinstance(text, ProseText):
                # Extraits du code : déjà lus par les règles dans le texte complet.
                if text in self._seen_prose:
                    continue
                self._seen_prose.add(text)
            elif text in self._seen_texts:
                continue
            else:
                self._seen_texts.add(text)
            batch.append(text)
        if not batch:
            return
        ner_spans: dict[int, list[Span]] = {}
        if self.ner is not None and self.ner.available:
            ner_inputs = [i for i, t in enumerate(batch) if not isinstance(t, CodeText)]
            for j, spans in self.ner.find_spans_many([str(batch[i]) for i in ner_inputs]):
                ner_spans[ner_inputs[j]] = spans
        for i, text in enumerate(batch):
            spans = self._static_spans(text) + [self._extend_person(text, s) for s in ner_spans.get(i, [])]
            for span in self._resolve(text, spans):
                if isinstance(text, ProseText) and span.source != "ner":
                    continue  # déjà compté dans le texte complet du fichier
                entity = self._register(span.text, span.category, span.source)
                if entity is not None:
                    entity.occurrences += 1

    def add_manual(self, value: str, category: str) -> Entity | None:
        """Ajout d'un terme oublié par l'utilisateur lors de la validation."""
        entity = self._register(value.strip(), normalize_category(category), "manuel")
        if entity is not None:
            entity.enabled = True
            entity.occurrences = max(entity.occurrences, self.count_occurrences(value.strip()))
        return entity

    def add_detected(self, value: str, category: str, source: str) -> Entity | None:
        """Valeur repérée par la structure du document (ex. colonne « Nom » d'Excel)."""
        value = value.strip()
        if not value or PLACEHOLDER_RE.fullmatch(value):
            return None
        entity = self._register(value, category, source)
        if entity is not None:
            entity.occurrences += 1
        return entity

    def pseudonymize_value(self, value: str, category: str) -> str:
        """Jeton pour une valeur entière (auteur d'un commentaire, nom d'expéditeur...)."""
        value = (value or "").strip()
        if not value:
            return value
        entity = self._register(value, category, "metadonnee")
        if entity is None or not entity.enabled:
            return value
        return entity.placeholder

    # ------------------------------------------------------------------ passe 2

    def apply(self, text: str) -> ApplyResult:
        if not text or not text.strip():
            return ApplyResult(text)
        spans = self._static_spans(text) + self._known_spans(text)
        replacements = []
        for span in self._resolve(text, spans):
            entity = self._lookup(span.text, span.category)
            if entity is None:
                entity = self._register(span.text, span.category, span.source)
            if entity is None or not entity.enabled:
                continue
            replacements.append(Replacement(span, entity.placeholder))
        if not replacements:
            return ApplyResult(text)
        out, pos = [], 0
        for rep in replacements:
            out.append(text[pos : rep.span.start])
            out.append(rep.placeholder)
            pos = rep.span.end
        out.append(text[pos:])
        return ApplyResult("".join(out), replacements)

    def anonymize_text(self, text: str) -> str:
        return self.apply(text).text

    # ------------------------------------------------------------------ consultation

    def count_occurrences(self, value: str) -> int:
        """Nombre d'apparitions d'une valeur dans les textes déjà analysés."""
        pattern = re.compile(
            r"(?<!\w)" + re.escape(value).replace(r"\ ", r"\s+") + r"(?!\w)", re.IGNORECASE
        )
        return sum(len(pattern.findall(t)) for t in self._seen_texts)

    def entity_list(self) -> list[Entity]:
        return sorted(self.entities.values(), key=lambda e: (e.category, e.placeholder))

    def set_enabled(self, placeholder: str, enabled: bool) -> None:
        self.entities[placeholder].enabled = enabled

    def mapping(self) -> dict[str, list[str]]:
        """Table de correspondance jeton -> valeurs d'origine (à protéger !)."""
        return {p: sorted(e.values) for p, e in self.entities.items()}

    # ------------------------------------------------------------------ interne

    def _static_spans(self, text: str) -> list[Span]:
        return find_rule_spans(text, self.config.rule_categories) + self.dictionary.find_spans(text)

    def _known_spans(self, text: str) -> list[Span]:
        if self._known_re is None:
            sensitive: set[str] = set()
            insensitive: set[str] = set()
            for placeholder, entity in self.entities.items():
                # Les valeurs trouvées par règles ou dictionnaire sont retrouvées par eux.
                if entity.sources <= {"regle", "dictionnaire"}:
                    continue
                for value in entity.values | self._aliases.get(placeholder, set()):
                    if len(value) < 2:
                        continue
                    if is_acronym(value):
                        sensitive.add(value)
                    else:
                        insensitive.add(value.casefold())
            patterns = []
            for forms, flags in ((sensitive, 0), (insensitive, re.IGNORECASE)):
                if forms:
                    alternatives = "|".join(
                        re.escape(f).replace(r"\ ", r"\s+") for f in sorted(forms, key=len, reverse=True)
                    )
                    patterns.append(re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", flags))
            self._known_re = patterns
        spans = []
        for pattern in self._known_re:
            for m in pattern.finditer(text):
                entity = self._lookup(m.group(), None)
                if entity is not None:
                    spans.append(Span(m.start(), m.end(), entity.category, "connu", m.group()))
        return spans

    def _resolve(self, text: str, spans: list[Span]) -> list[Span]:
        protected = [m.span() for m in PLACEHOLDER_RE.finditer(text)]
        candidates = []
        for span in spans:
            if any(span.start < pe and ps < span.end for ps, pe in protected):
                continue
            if span.source != "dictionnaire" and self.dictionary.is_excluded(span.text):
                continue
            candidates.append(span)
        candidates.sort(key=lambda s: (-s.length, SOURCE_PRIORITY.get(s.source, 9), s.start))
        chosen: list[Span] = []
        for span in candidates:
            if all(span.end <= c.start or span.start >= c.end for c in chosen):
                chosen.append(span)
        return sorted(chosen, key=lambda s: s.start)

    _UPPER_WORD = re.compile(r"[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\-]+")

    def _extend_person(self, text: str, span: Span) -> Span:
        """« DUPONT Jean » : le modèle ne repère souvent que « Jean ». On rattache au
        nom les mots voisins écrits entièrement en majuscules (sauf termes du dictionnaire)."""
        if span.category != "PERSONNE":
            return span
        start, end = span.start, span.end
        for _ in range(2):  # à gauche
            m = re.search(r"([^\s]+)[ \t]$", text[:start])
            if not m or not self._UPPER_WORD.fullmatch(m.group(1)) or self._is_known_term(m.group(1)):
                break
            start = m.start(1)
        for _ in range(2):  # à droite
            m = re.match(r"[ \t]([^\s,;.()]+)", text[end:])
            if not m or not self._UPPER_WORD.fullmatch(m.group(1)) or self._is_known_term(m.group(1)):
                break
            end += m.end(1)
        if (start, end) == (span.start, span.end):
            return span
        return Span(start, end, span.category, span.source, text[start:end])

    def _is_known_term(self, word: str) -> bool:
        return (self.dictionary.category_for(word) is not None or self.dictionary.is_excluded(word)
                or word.casefold() in COMMON_FALSE_POSITIVES)

    def _key(self, value: str, category: str | None) -> str:
        if category is None:
            return normalize_value("", value)
        return normalize_value(category, value)

    def _lookup(self, value: str, category: str | None) -> Entity | None:
        keys = {self._key(value, category)}
        if category not in CASE_SENSITIVE_CATEGORIES:
            keys.add(self._key(value, None))
        for key in keys:
            placeholder = self._index.get(key)
            if placeholder is not None:
                return self.entities[placeholder]
        return None

    def _register(self, value: str, category: str, source: str) -> Entity | None:
        if not value or self.dictionary.is_excluded(value):
            return None
        entity = self._lookup(value, category)
        if entity is None:
            canonical = self.dictionary.canonical_for(value)
            if canonical and canonical != value:
                entity = self._lookup(canonical, None)
            if entity is None:
                category = self.dictionary.category_for(value) or category
                self._counters[category] += 1
                placeholder = f"[{category}_{self._counters[category]}]"
                entity = Entity(placeholder, category)
                self.entities[placeholder] = entity
            if canonical:
                self._index.setdefault(self._key(canonical, None), entity.placeholder)
            self._index[self._key(value, category)] = entity.placeholder
            if entity.category not in CASE_SENSITIVE_CATEGORIES:
                self._index.setdefault(self._key(value, None), entity.placeholder)
            if entity.category == "PERSONNE" and self.config.split_person_names:
                self._add_name_parts(entity, value)
            self._known_re = None
        if value not in entity.values:
            entity.values.add(value)
            self._known_re = None
        entity.sources.add(source)
        return entity

    def _add_name_parts(self, entity: Entity, value: str) -> None:
        parts = re.split(r"[\s]+", value)
        if len(parts) < 2:
            return
        for part in parts:
            token = part.strip(".,;:()")
            if (
                len(token) >= 3
                and token[0].isupper()
                and token.casefold() not in COMMON_FALSE_POSITIVES
                and not self.dictionary.is_excluded(token)
                and self._key(token, None) not in self._index
            ):
                self._index[self._key(token, None)] = entity.placeholder
                self._aliases.setdefault(entity.placeholder, set()).add(token)
