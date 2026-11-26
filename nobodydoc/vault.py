"""Tables de correspondance chiffrées et restauration des vraies valeurs.

Après chaque anonymisation, la correspondance jeton -> valeur d'origine est
enregistrée, chiffrée (AES-256-GCM), dans le profil de l'utilisateur. La clé
est elle-même protégée par Windows (DPAPI) : seul ce compte Windows, sur ce
poste, peut relire les tables. Aucun mot de passe à retenir.

Quand l'IA ou le prestataire renvoie un texte ou un document contenant des
jetons, ``MappingTable.apply`` remet les vraies valeurs. Le restaurateur a la
même interface qu'une session d'anonymisation, ce qui permet de réutiliser
tels quels les lecteurs de fichiers (Word, Excel, PowerPoint, mails, texte).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .entities import Span
from .session import AnonymizationSession, ApplyResult, Replacement
from .settings import app_dir

MAGIC = b"NDT1"
KEY_FILE = "cle.bin"


# ----------------------------------------------------------------------------- clé


def _dpapi(data: bytes, unprotect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if unprotect:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), ctypes.c_wchar_p("NobodyDoc"), None, None,
                                      None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError("Windows a refusé de (dé)chiffrer la clé de NobodyDoc.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _load_or_create_key(directory: Path) -> bytes:
    path = directory / KEY_FILE
    if path.exists():
        raw = path.read_bytes()
        return _dpapi(raw, unprotect=True) if sys.platform == "win32" else raw
    key = secrets.token_bytes(32)
    directory.mkdir(parents=True, exist_ok=True)
    stored = _dpapi(key, unprotect=False) if sys.platform == "win32" else key
    path.write_bytes(stored)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return key


def _encrypt(key: bytes, payload: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, MAGIC)


def _decrypt(key: bytes, data: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not data.startswith(MAGIC):
        raise ValueError("Ce fichier n'est pas une table NobodyDoc.")
    try:
        return AESGCM(key).decrypt(data[4:16], data[16:], MAGIC)
    except InvalidTag as exc:
        raise ValueError(
            "Table illisible : elle a été créée par un autre compte Windows ou sur un autre poste."
        ) from exc


# ----------------------------------------------------------------------------- table


@dataclass
class TableEntry:
    placeholder: str
    category: str
    values: list[str]

    @property
    def original(self) -> str:
        """Valeur remise à la place du jeton : la forme la plus complète."""
        return max(self.values, key=len) if self.values else self.placeholder


@dataclass
class MappingTable:
    created: datetime
    files: list[str]
    entries: dict[str, TableEntry] = field(default_factory=dict)
    path: Path | None = None
    _patterns: list[re.Pattern] | None = field(default=None, repr=False)

    # -- construction / sérialisation ------------------------------------------

    @classmethod
    def from_session(cls, session: AnonymizationSession, files: list[str]) -> "MappingTable":
        entries = {
            e.placeholder: TableEntry(e.placeholder, e.category, sorted(e.values))
            for e in session.entities.values()
            if e.enabled and e.values
        }
        return cls(datetime.now().replace(microsecond=0), list(files), entries)

    def to_json(self) -> bytes:
        return json.dumps({
            "version": 1,
            "creee": self.created.isoformat(),
            "fichiers": self.files,
            "entites": [{"jeton": e.placeholder, "categorie": e.category, "valeurs": e.values}
                        for e in self.entries.values()],
        }, ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes, path: Path | None = None) -> "MappingTable":
        obj = json.loads(data.decode("utf-8"))
        entries = {e["jeton"]: TableEntry(e["jeton"], e["categorie"], list(e["valeurs"])) for e in obj["entites"]}
        return cls(datetime.fromisoformat(obj["creee"]), list(obj["fichiers"]), entries, path)

    @property
    def label(self) -> str:
        names = ", ".join(Path(f).name for f in self.files[:3])
        if len(self.files) > 3:
            names += f" et {len(self.files) - 3} autre(s)"
        return f"{self.created:%d/%m/%Y %H:%M} — {names} ({len(self.entries)} éléments)"

    # -- restauration -------------------------------------------------------------

    def _compiled(self) -> list[re.Pattern]:
        if self._patterns is None:
            categories = sorted({e.category for e in self.entries.values()}, key=len, reverse=True)
            if not categories:
                self._patterns = []
            else:
                alt = "|".join(re.escape(c) for c in categories)
                self._patterns = [
                    # [PERSONNE_1], [Personne 1], [ PERSONNE-1 ] : l'IA réécrit parfois les jetons
                    re.compile(rf"\[\s*({alt})[ _\-]?(\d+)\s*\]", re.IGNORECASE),
                    # PERSONNE_1 sans crochets, seulement en majuscules avec « _ »
                    re.compile(rf"(?<![\w\[])({alt})_(\d+)(?![\w\]])"),
                ]
        return self._patterns

    def find_tokens(self, text: str) -> list[tuple[int, int, str]]:
        """(début, fin, jeton normalisé) pour chaque jeton présent dans le texte."""
        found = []
        taken: list[tuple[int, int]] = []
        for pattern in self._compiled():
            for m in pattern.finditer(text):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append(m.span())
                found.append((m.start(), m.end(), f"[{m.group(1).upper()}_{int(m.group(2))}]"))
        return sorted(found)

    def unknown_tokens(self, text: str) -> list[str]:
        return sorted({tok for _, _, tok in self.find_tokens(text) if tok not in self.entries})

    def apply(self, text: str) -> ApplyResult:
        if not text:
            return ApplyResult(text)
        replacements, out, pos = [], [], 0
        for start, end, token in self.find_tokens(text):
            entry = self.entries.get(token)
            if entry is None:
                continue
            out.append(text[pos:start])
            out.append(entry.original)
            pos = end
            replacements.append(Replacement(Span(start, end, entry.category, "table", text[start:end]), entry.original))
        if not replacements:
            return ApplyResult(text)
        out.append(text[pos:])
        return ApplyResult("".join(out), replacements)

    def anonymize_text(self, text: str) -> str:  # interface commune avec la session
        return self.apply(text).text

    def pseudonymize_value(self, value: str, category: str) -> str:
        return self.apply(value).text if value else value


# ----------------------------------------------------------------------------- stockage


class TableStore:
    """Dossier des tables chiffrées (par défaut %APPDATA%\\NobodyDoc\\tables)."""

    def __init__(self, directory: Path | None = None):
        self.base = directory or app_dir()
        self.directory = self.base / "tables"

    def _key(self) -> bytes:
        return _load_or_create_key(self.base)

    def save(self, table: MappingTable) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{table.created:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.ndtable"
        path.write_bytes(_encrypt(self._key(), table.to_json()))
        table.path = path
        return path

    def save_session(self, session: AnonymizationSession, files: list[str]) -> Path:
        return self.save(MappingTable.from_session(session, files))

    def load(self, path: Path) -> MappingTable:
        return MappingTable.from_json(_decrypt(self._key(), Path(path).read_bytes()), Path(path))

    def list(self) -> list[MappingTable]:
        """Tables lisibles, de la plus récente à la plus ancienne."""
        if not self.directory.exists():
            return []
        tables = []
        for path in sorted(self.directory.glob("*.ndtable"), reverse=True):
            try:
                tables.append(self.load(path))
            except (ValueError, OSError):
                continue
        return tables

    def delete(self, table: MappingTable) -> None:
        if table.path is not None and table.path.exists():
            table.path.unlink()

    def delete_older_than(self, days: int) -> int:
        """Purge (minimisation RGPD) : supprime les tables de plus de ``days`` jours."""
        removed = 0
        now = datetime.now()
        for table in self.list():
            if (now - table.created).days >= days:
                self.delete(table)
                removed += 1
        return removed
