"""Détection par règles : données à forme fixe (e-mails, téléphones, IBAN...)."""

from __future__ import annotations

import re
from typing import Callable, Iterator

from ..entities import Span

# --- Validateurs ---------------------------------------------------------------


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _iban_ok(candidate: str) -> bool:
    iban = re.sub(r"\s", "", candidate).upper()
    if not 15 <= len(iban) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    return int(number) % 97 == 1


def _nir_ok(candidate: str) -> bool:
    raw = re.sub(r"[\s.]", "", candidate).upper()
    body, key = raw[:13], raw[13:]
    if len(body) != 13:
        return False
    if not key:
        return True
    numeric = body.replace("2A", "19").replace("2B", "18")
    if not numeric.isdigit():
        return False
    return 97 - int(numeric) % 97 == int(key)


# --- Motifs --------------------------------------------------------------------

_STREET_TYPES = (
    r"rue|avenue|av\.?|boulevard|bd|place|pl\.|chemin|ch\.|all[ée]e|impasse|route|rte|"
    r"quai|cours|square|voie|passage|faubourg|fbg|rond-point|esplanade|parvis|"
    r"promenade|sentier|lotissement|r[ée]sidence|hameau|lieu-dit|cit[ée]|villa|mail|"
    r"zone|za|zi|zac|parc"
)
_UPPER = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ"
_CITY = (
    rf"(?!CEDEX\b)[{_UPPER}][\w'’\-]*"
    rf"(?:[ \-](?:(?:sur|sous|en|lès|les|le|la|de|du|des|d'|l')[ \-]?)?(?!CEDEX\b)[{_UPPER}][\w'’\-]*){{0,3}}"
)

Finder = Callable[[str], Iterator[tuple[int, int]]]


def _regex_finder(pattern: str, flags: int = 0, validator=None, group: int = 0) -> Finder:
    compiled = re.compile(pattern, flags)

    def find(text: str) -> Iterator[tuple[int, int]]:
        for m in compiled.finditer(text):
            start, end = m.span(group)
            value = text[start:end]
            if validator is None or validator(value):
                yield start, end

    return find


def _iban_finder(text: str) -> Iterator[tuple[int, int]]:
    # Un IBAN peut être suivi d'un mot en majuscules (« BIC ») : on raccourcit
    # le candidat jusqu'à trouver une clé de contrôle valide.
    for m in re.finditer(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,32}", text):
        start, end = m.span()
        while end - start >= 15:
            if _iban_ok(text[start:end]):
                yield start, end
                break
            end -= 1
            while end > start and text[end - 1] == " ":
                end -= 1


def _url_finder(text: str) -> Iterator[tuple[int, int]]:
    for m in re.finditer(r"\b(?:https?://|www\.)[^\s<>\"'\]\)]+", text, re.I):
        start, end = m.span()
        while end > start and text[end - 1] in ".,;:!?":
            end -= 1
        yield start, end


RULES: dict[str, list[Finder]] = {
    "EMAIL": [
        _regex_finder(r"[\w.+\-']+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}"),
    ],
    "URL": [_url_finder],
    "IBAN": [_iban_finder],
    "CARTE_BANCAIRE": [
        _regex_finder(
            r"(?<![\d\w])[2-6]\d{3}(?:[ \-]?\d{4}){2}[ \-]?\d{1,7}(?![\d\w])",
            validator=lambda v: 13 <= len(re.sub(r"\D", "", v)) <= 19
            and _luhn_ok(re.sub(r"\D", "", v)),
        )
    ],
    "NIR": [
        _regex_finder(
            r"(?<![\d\w])[12][ .]?\d{2}[ .]?(?:0[1-9]|1[0-2]|[2-9]\d)[ .]?(?:\d{2}|2[ABab])"
            r"[ .]?\d{3}[ .]?\d{3}(?:[ .]?\d{2})?(?![\d\w])",
            validator=_nir_ok,
        )
    ],
    "ID_ENTREPRISE": [
        # SIREN / SIRET précédés de leur libellé
        _regex_finder(
            r"\bSIRE[NT]\s*(?:n°|no|:)?\s*:?\s*(\d{3}[ .]?\d{3}[ .]?\d{3}(?:[ .]?\d{5})?)",
            flags=re.I,
            group=1,
        ),
        # SIRET formaté seul (14 chiffres valides selon Luhn)
        _regex_finder(
            r"(?<![\d\w])\d{3} \d{3} \d{3} \d{5}(?![\d\w])",
            validator=lambda v: _luhn_ok(re.sub(r"\D", "", v)),
        ),
        # TVA intracommunautaire française
        _regex_finder(r"\bFR ?[0-9A-Z]{2} ?\d{3} ?\d{3} ?\d{3}\b"),
    ],
    "TELEPHONE": [
        # France : 01 23 45 67 89, +33 (0)1 23 45 67 89, 0033 1 23...
        _regex_finder(
            r"(?<![\w+])(?:(?:\+|00)33[ .\-]?(?:\(0\)[ .\-]?)?|0)[1-9](?:[ .\-]?\d{2}){4}(?!\d)"
        ),
        # International avec indicatif « + »
        _regex_finder(
            r"(?<![\w+])\+(?!33)\d{1,3}(?:[ .\-]?\(?\d{1,4}\)?){2,6}(?!\d)",
            validator=lambda v: 8 <= len(re.sub(r"\D", "", v)) <= 15,
        ),
    ],
    "IP": [
        _regex_finder(
            r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?!\.?\d)"
        )
    ],
    "ADRESSE": [
        # 12 bis rue des Lilas / 3, avenue Foch
        _regex_finder(
            rf"(?<![\w])\d{{1,4}}(?: ?(?:bis|ter|quater|[a-cA-C]))?\s*,?\s+(?:{_STREET_TYPES})\b\.?"
            r"[ \t]+[^\n,;()]{1,60}?(?=\s*[,;\n()]|\s+\d{5}\b|$)",
            flags=re.I,
        ),
        # Code postal + ville (75001 Paris, 69 003 LYON CEDEX 03)
        _regex_finder(rf"(?<![\w])(?:\d{{5}}|\d{{2}} \d{{3}})[ \t]+{_CITY}(?:[ \t]+CEDEX(?:[ \t]?\d{{1,2}})?)?"),
        # Boîte postale
        _regex_finder(r"\b(?:BP|CS|TSA)[ \t]?\d{2,6}\b"),
    ],
}

ALL_RULE_CATEGORIES = tuple(RULES)


def find_rule_spans(text: str, categories=ALL_RULE_CATEGORIES) -> list[Span]:
    spans: list[Span] = []
    seen: set[tuple[int, int, str]] = set()
    for category in categories:
        for finder in RULES.get(category, ()):
            for start, end in finder(text):
                if end > start and (start, end, category) not in seen:
                    seen.add((start, end, category))
                    spans.append(Span(start, end, category, "regle", text[start:end]))
    return _merge_addresses(text, spans)


def _merge_addresses(text: str, spans: list[Span]) -> list[Span]:
    """Fusionne « 12 rue X » et « 75001 Paris » quand ils se suivent."""
    addresses = sorted((s for s in spans if s.category == "ADRESSE"), key=lambda s: s.start)
    others = [s for s in spans if s.category != "ADRESSE"]
    merged: list[Span] = []
    for span in addresses:
        if merged and re.fullmatch(r"[\s,\-–]{0,4}", text[merged[-1].end : span.start] or ""):
            prev = merged.pop()
            end = max(prev.end, span.end)
            merged.append(Span(prev.start, end, "ADRESSE", "regle", text[prev.start : end]))
        elif merged and span.start < merged[-1].end:
            prev = merged.pop()
            end = max(prev.end, span.end)
            merged.append(Span(prev.start, end, "ADRESSE", "regle", text[prev.start : end]))
        else:
            merged.append(span)
    return others + merged
