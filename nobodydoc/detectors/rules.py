"""Détection par règles : données à forme fixe (e-mails, téléphones, IBAN...)."""

from __future__ import annotations

import ipaddress
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


def _email_finder(text: str) -> Iterator[tuple[int, int]]:
    # L'apostrophe n'est admise qu'à l'intérieur (o'neil) : dans 'jean@acme.fr'
    # (SQL, code), les guillemets ne font pas partie de l'adresse.
    for m in _EMAIL_RE.finditer(text):
        # « user:mdp@serveur » dans une chaîne de connexion n'est pas un e-mail.
        if _URI_USERINFO_RE.search(text, max(0, m.start() - 200), m.start()):
            continue
        yield m.span()


_EMAIL_RE = re.compile(r"[\w+\-](?:[\w.+\-']*[\w+\-])?@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}")
_URI_USERINFO_RE = re.compile(r"://[^\s/@'\"]*\Z")

# --- Code, configuration et chaînes de connexion -------------------------------

# Valeurs qui ne sont pas des données : variables, types, paramètres de requête...
_NOT_A_VALUE = {
    "none", "null", "nil", "true", "false", "undefined", "str", "string", "int", "number",
    "bool", "boolean", "any", "object", "bytes", "char", "varchar", "text", "optional",
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "*", "example", "changeme", "xxx", "****",
}
_CODE_PREFIXES = re.compile(
    r"(?:self|this|os|config|conf|cfg|settings|env|process|cls|ctx|args|params|options|opts|"
    r"request|req|session|app|data|credentials|creds|secrets|vault)\.", re.I
)

_SECRET_KEYS = (
    r"(?:[\w\-]*[_.\-])?(?:pass|pwd|mdp|token|secret|secret[_\-]?key|api[_\-]?key|"
    r"access[_\-]?key|private[_\-]?key|credentials?|mot_de_passe|auth[_\-]?token)"
    r"|[\w\-]*(?:password|passwd|apikey|accountkey|sharedaccesskey)"
    r"|mot\s+de\s+passe"
)
_USER_KEYS = (
    r"(?:[\w\-]*[_.\-])?(?:user(?:[_\-]?(?:name|id))?|username|login|uid)|user\s+id"
)
_HOST_KEYS = (
    r"(?:[\w\-]*[_.\-])?(?:host|hostname|host_name|server|servername|server_name)"
    r"|data\s+source|address|addr|network\s+address"
)
_KV_TEMPLATE = (
    r"(?<![\w.\-])(?:{keys})[\"']?\]?"
    r"(?:\s*(?:=>|:=|=|:)\s*|\s+(?=[\"']))"
    r"(?:\"(?P<dq>[^\"\n]*)\"|'(?P<sq>[^'\n]*)'|(?P<bare>[^\s;&,'\"()\[\]{{}}<>]+))"
)


def _kv_finder(keys: str, numbers_ok: bool = True) -> Finder:
    compiled = re.compile(_KV_TEMPLATE.format(keys=keys), re.I)

    def find(text: str) -> Iterator[tuple[int, int]]:
        for m in compiled.finditer(text):
            group = next(g for g in ("dq", "sq", "bare") if m.group(g) is not None)
            start, end = m.span(group)
            value = text[start:end]
            if _plausible_value(value, m.group(0)[: m.start(group) - m.start()], group == "bare",
                                text[end:end + 40], numbers_ok):
                yield start, end

    return find


def _plausible_value(value: str, key: str, bare: bool, after: str, numbers_ok: bool) -> bool:
    if not value.strip() or re.search(r"\s", value):  # libellé (« Mot de passe »), pas un secret
        return False
    low = value.casefold()
    key_word = re.sub(r"[\"'\]\s=:>]+$", "", key).casefold()
    if low in _NOT_A_VALUE or (key_word and key_word in low) or len(set(value)) == 1:
        return False
    if value[0] in "$@:?%{<*#" or "{{" in value or "${" in value:  # paramètre, gabarit
        return False
    if not numbers_ok and value.isdigit():
        return False
    if bare:
        if after[:1] and after[:1] in "([":  # appel de fonction : password = get_password()
            return False
        if "=" not in key and re.match(r"[ \t]+[^\W\d_]{2,}", after):  # phrase : « mot de passe : voir avec la DSI »
            return False
        if _CODE_PREFIXES.match(value):
            return False
    return True


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
        return True
    except ValueError:
        return False


# scheme://utilisateur:mot_de_passe@serveur:port/base (PostgreSQL, MySQL, MongoDB,
# Redis, AMQP, FTP, LDAP, JDBC...). Les liens web http(s) sont traités en entier.
_URI_RE = re.compile(
    r"\b(?:jdbc:)?(?!https?://)[a-z][a-z0-9+.\-]{1,20}://"
    r"(?:(?P<user>[^\s:@/'\"]+)(?::(?P<password>[^\s@'\"]+))?@)?"
    r"(?P<host>\[[0-9A-Fa-f:.]+\]|[\w\-]+(?:\.[\w\-]+)*)",
    re.I,
)


def _uri_part_finder(part: str) -> Finder:
    def find(text: str) -> Iterator[tuple[int, int]]:
        for m in _URI_RE.finditer(text):
            if m.group(part) is None:
                continue
            value = m.group(part)
            if part == "host" and (_is_ip(value) or value.casefold() in _NOT_A_VALUE):
                continue  # les adresses IP sont prises par leur propre règle
            if part == "password" and (value[0] in "$%{<*" or len(set(value)) == 1):
                continue
            yield m.span(part)

    return find


# Serveurs internes : srv-paie01.acme.local, db.prod.internal...
_INTERNAL_HOST_RE = re.compile(
    r"(?<![\w.\-@])(?!(?:com|org|net|io|fr|eu|de|java|javax|android)\.)"
    r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)*"
    r"\.(?:local|lan|internal|intra|intranet|corp|localdomain)(?![\w\-]|\.\w)",
    re.I,
)


def _ipv6_finder(text: str) -> Iterator[tuple[int, int]]:
    for m in re.finditer(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])", text):
        value = m.group()
        if len(value) < 6 or value.count(":") < 2:
            continue
        try:
            ipaddress.IPv6Address(value)
        except ValueError:
            continue
        yield m.span()


# Formats de clés reconnaissables par leur préfixe.
_KEY_PATTERNS = [
    r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b",  # AWS
    r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b",  # GitHub
    r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b",
    r"\bglpat-[A-Za-z0-9_\-]{20,}",  # GitLab
    r"\bxox[abposr]-[A-Za-z0-9\-]{10,}",  # Slack
    r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b",  # Stripe
    r"\bAIza[0-9A-Za-z_\-]{35}",  # Google
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}",  # OpenAI, Anthropic...
    r"\beyJ[A-Za-z0-9_\-]{5,}\.eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]+",  # JWT
    r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z]+ )*PRIVATE KEY-----",
]


RULES: dict[str, list[Finder]] = {
    "EMAIL": [_email_finder],
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
        ),
        _ipv6_finder,
    ],
    "SECRET": [
        *(_regex_finder(p) for p in _KEY_PATTERNS),
        _regex_finder(r"\b(?:Bearer|Basic)\s+([A-Za-z0-9\-._~+/]{16,}=*)", group=1),
        _regex_finder(r"\bIDENTIFIED\s+BY\s+'([^'\n]+)'", flags=re.I, group=1),
        _uri_part_finder("password"),
        _kv_finder(_SECRET_KEYS),
    ],
    "IDENTIFIANT": [
        _uri_part_finder("user"),
        _kv_finder(_USER_KEYS, numbers_ok=False),
    ],
    "HOTE": [
        _uri_part_finder("host"),
        _regex_finder(_INTERNAL_HOST_RE.pattern, flags=re.I),
        _kv_finder(_HOST_KEYS),
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
