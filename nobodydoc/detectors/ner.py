"""Détection des noms de personnes et d'organisations par un modèle spaCy local.

Le modèle tourne entièrement sur le poste : aucune donnée ne sort.
Si aucun modèle n'est installé, la détection par règles et par dictionnaire
continue de fonctionner seule.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Iterator

from ..entities import Span

log = logging.getLogger(__name__)

DEFAULT_MODELS = ("fr_core_news_md", "fr_core_news_sm", "fr_core_news_lg")
LABEL_TO_CATEGORY = {"PER": "PERSONNE", "ORG": "ORGANISATION", "LOC": "LIEU"}

_TITLES = re.compile(
    r"^(?:(?:m\.|mr\.?|mme\.?|mlle\.?|me\.?|dr\.?|pr\.?|monsieur|madame|mademoiselle|"
    r"ma[iî]tre|docteur|professeur|cher|ch[eè]re)\s+)+",
    re.IGNORECASE,
)

# Mots fréquents en tête de phrase ou de mail que le modèle prend parfois pour des noms.
COMMON_FALSE_POSITIVES = {
    "bonjour", "bonsoir", "cordialement", "salutations", "merci", "objet", "madame",
    "monsieur", "cher", "chère", "bien", "bonne", "réf", "pj", "cc", "tél", "tel",
    "mobile", "fax", "email", "e-mail", "mail", "adresse", "date", "total", "nom",
    "prénom", "société", "client", "fournisseur", "projet", "annexe", "page", "note",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre", "rgpd", "tva", "ttc", "ht",
    "téléphone", "telephone", "montant", "ville", "pays", "statut", "commentaire",
    "commentaires", "description", "référence", "reference", "contact", "contacts",
    "responsable", "direction", "service", "équipe", "objectif", "objectifs",
    "résumé", "conclusion", "introduction", "sommaire", "ordre du jour",
}


class NerDetector:
    def __init__(self, model: str | None = None, labels: Iterable[str] = ("PER", "ORG")):
        self.labels = set(labels)
        self.model_name: str | None = None
        self._nlp = None
        self._load(model)

    @property
    def available(self) -> bool:
        return self._nlp is not None

    def _load(self, model: str | None) -> None:
        try:
            import spacy
        except ImportError:
            log.warning("spaCy n'est pas installé : détection des noms désactivée.")
            return
        for name in ([model] if model else DEFAULT_MODELS):
            try:
                self._nlp = spacy.load(name, disable=["lemmatizer", "morphologizer", "attribute_ruler"])
                self.model_name = name
                self._nlp.max_length = 2_000_000
                return
            except (OSError, ValueError):
                continue
        log.warning("Aucun modèle spaCy français trouvé : détection des noms désactivée.")

    def find_spans_many(self, texts: list[str]) -> Iterator[tuple[int, list[Span]]]:
        """Analyse plusieurs textes (plus rapide qu'un par un). Renvoie (index, spans)."""
        if not self.available:
            return
        for idx, doc in enumerate(self._nlp.pipe(texts, batch_size=64)):
            spans = []
            for ent in doc.ents:
                category = LABEL_TO_CATEGORY.get(ent.label_)
                if category is None or ent.label_ not in self.labels:
                    continue
                span = self._clean(texts[idx], ent.start_char, ent.end_char, category)
                if span is not None:
                    spans.append(span)
            yield idx, spans

    def find_spans(self, text: str) -> list[Span]:
        for _, spans in self.find_spans_many([text]):
            return spans
        return []

    @staticmethod
    def _clean(text: str, start: int, end: int, category: str) -> Span | None:
        value = text[start:end]
        # Retire civilités (« Mme Martin » -> « Martin ») et ponctuation autour.
        m = _TITLES.match(value)
        if m:
            start += m.end()
        while start < end and not text[start].isalnum():
            start += 1
        while end > start and not text[end - 1].isalnum():
            end -= 1
        value = text[start:end]
        if len(value) < 2 or not any(c.isupper() for c in value):
            return None
        if value.casefold() in COMMON_FALSE_POSITIVES:
            return None
        # Un mot seul formant tout le texte (en-tête de colonne, titre) : le modèle
        # se trompe trop souvent sans contexte. S'il s'agit d'un vrai nom vu
        # ailleurs dans une phrase, il sera de toute façon masqué ici aussi.
        if " " not in value and text.strip(" \t\n:.-") == value:
            return None
        if re.fullmatch(r"[\d\W_]+", value) or "[" in value or "]" in value or "@" in value:
            return None
        # Les lignes entières captées par erreur (titres, en-têtes) sont rejetées.
        if len(value.split()) > 6 or "\n" in value:
            return None
        return Span(start, end, category, "ner", value)
