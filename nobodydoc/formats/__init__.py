"""Registre des formats pris en charge."""

from __future__ import annotations

from pathlib import Path

from .code import CodeHandler
from .email_handler import EmailHandler
from .ooxml import OoxmlHandler
from .text import TextHandler

_OOXML = OoxmlHandler()
_TEXT = TextHandler()


def handler_for(ext: str):
    ext = ext.lower()
    if ext in OoxmlHandler.extensions:
        return _OOXML
    if ext in TextHandler.extensions:
        return _TEXT
    if ext in EmailHandler.extensions:
        return _EMAIL
    if ext in CodeHandler.extensions:
        return CodeHandler.for_extension(ext)
    return None


_EMAIL = EmailHandler(handler_for)

SUPPORTED_EXTENSIONS = (
    OoxmlHandler.extensions + TextHandler.extensions + EmailHandler.extensions + CodeHandler.extensions
)


def split_name(path: Path) -> tuple[str, str]:
    """(nom, extension) d'un fichier ; « .env » et « .env.prod » comptent comme .env."""
    name = path.name
    if name.lower() == ".env" or name.lower().startswith(".env."):
        return name[1:], ".env"
    return path.stem, path.suffix


def file_extension(path: Path) -> str:
    return split_name(path)[1]
