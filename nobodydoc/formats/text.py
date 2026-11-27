"""Fichiers texte : .txt, .csv, .md, .json, .log, .tsv."""

from __future__ import annotations

from typing import Iterator

from ..session import AnonymizationSession
from .base import FileReport

ENCODINGS = ("utf-8", "cp1252", "latin-1")


def decode(data: bytes) -> tuple[str, str]:
    """Décode et renvoie l'encodage à réutiliser pour écrire la copie.

    La marque d'ordre des octets (BOM) n'est remise que si l'original en avait une :
    en ajouter une gênerait certains scripts (#!/bin/sh) et outils.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace"), "latin-1"


class TextHandler:
    extensions = (".txt", ".csv", ".md", ".json", ".log", ".tsv")

    def iter_texts(self, data: bytes) -> Iterator[str]:
        text, _ = decode(data)
        # Par blocs de paragraphes : le modèle de langue préfère des textes courts.
        for block in text.split("\n\n"):
            if block.strip():
                yield block

    def anonymize(self, data: bytes, session: AnonymizationSession, report: FileReport) -> bytes:
        text, encoding = decode(data)
        result = session.apply(text)
        report.count(result.replacements)
        # Même encodage qu'à l'origine : les jetons sont en ASCII.
        return result.text.encode(encoding, errors="replace")
