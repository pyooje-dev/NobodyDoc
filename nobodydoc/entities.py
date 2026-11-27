"""Types de base : catégories, spans détectés et normalisation des valeurs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Libellés lisibles des catégories intégrées (les catégories du dictionnaire
# de l'entreprise s'ajoutent librement : CLIENT, PRODUIT, DEPARTEMENT...).
CATEGORY_LABELS = {
    "PERSONNE": "Nom de personne",
    "ORGANISATION": "Entreprise / organisation",
    "LIEU": "Lieu",
    "EMAIL": "Adresse e-mail",
    "TELEPHONE": "Téléphone",
    "IBAN": "IBAN",
    "CARTE_BANCAIRE": "Carte bancaire",
    "NIR": "Numéro de sécurité sociale",
    "ID_ENTREPRISE": "SIREN / SIRET / TVA",
    "ADRESSE": "Adresse postale",
    "URL": "Site web",
    "IP": "Adresse IP",
    "HOTE": "Nom de serveur",
    "IDENTIFIANT": "Identifiant de connexion",
    "SECRET": "Mot de passe / clé secrète",
    "CLIENT": "Client",
    "PRODUIT": "Produit",
    "PROJET": "Projet",
    "DEPARTEMENT": "Département",
    "ACRONYME": "Acronyme",
    "DIVERS": "Divers",
}

# Ordre de priorité quand deux détections se chevauchent avec la même longueur.
SOURCE_PRIORITY = {"dictionnaire": 0, "regle": 1, "connu": 2, "ner": 3}

PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")

_DIGIT_CATEGORIES = {"TELEPHONE", "CARTE_BANCAIRE", "NIR"}
_ALNUM_CATEGORIES = {"IBAN", "ID_ENTREPRISE"}
# Valeurs comparées à l'identique : « Abc1 » et « aBC1 » sont deux secrets différents.
CASE_SENSITIVE_CATEGORIES = {"SECRET"}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    category: str
    source: str
    text: str

    @property
    def length(self) -> int:
        return self.end - self.start


class CodeText(str):
    """Texte complet d'un fichier de code : règles et dictionnaire, sans modèle de langue
    (qui prendrait les noms de variables ou de tables pour des noms de personnes)."""


class ProseText(str):
    """Commentaire ou chaîne de caractères extrait du code : lu par le modèle de langue."""


@dataclass
class Entity:
    """Une valeur sensible et toutes ses variantes, remplacées par un seul jeton."""

    placeholder: str
    category: str
    values: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    occurrences: int = 0
    enabled: bool = True

    @property
    def display_value(self) -> str:
        return max(self.values, key=len) if self.values else ""


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_category(category: str) -> str:
    cat = strip_accents(category).upper().strip()
    cat = re.sub(r"[^A-Z0-9]+", "_", cat).strip("_")
    return cat or "DIVERS"


def normalize_value(category: str, value: str) -> str:
    """Clé de rapprochement : deux écritures d'une même valeur donnent la même clé."""
    if category in _DIGIT_CATEGORIES:
        digits = re.sub(r"\D", "", value)
        if category == "TELEPHONE":
            if digits.startswith("0033"):
                digits = "0" + digits[4:]
            elif digits.startswith("33") and len(digits) == 11:
                digits = "0" + digits[2:]
        return f"{category}:{digits}"
    if category in CASE_SENSITIVE_CATEGORIES:
        return f"{category}:{value}"
    if category in _ALNUM_CATEGORIES:
        return f"{category}:" + re.sub(r"[^0-9A-Za-z]", "", value).upper()
    text = strip_accents(value).casefold()
    text = re.sub(r"\s+", " ", text).strip(" .,;:")
    return text
