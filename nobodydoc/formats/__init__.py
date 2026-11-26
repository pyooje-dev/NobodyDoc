"""Registre des formats pris en charge."""

from __future__ import annotations

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
    return None


_EMAIL = EmailHandler(handler_for)

SUPPORTED_EXTENSIONS = OoxmlHandler.extensions + TextHandler.extensions + EmailHandler.extensions
