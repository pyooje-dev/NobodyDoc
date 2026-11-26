"""Rapport de traitement d'un fichier."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class FileReport:
    source: str
    output: str = ""
    replacements: Counter = field(default_factory=Counter)
    metadata: int = 0
    images: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def count(self, replacements) -> None:
        for rep in replacements:
            self.replacements[rep.span.category] += 1

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def total(self) -> int:
        return sum(self.replacements.values())

    def finalize(self) -> None:
        if self.images:
            self.warn(
                f"{self.images} image(s) non analysée(s) : vérifiez qu'elles ne montrent "
                "pas de données personnelles (captures d'écran, signatures, logos)."
            )
