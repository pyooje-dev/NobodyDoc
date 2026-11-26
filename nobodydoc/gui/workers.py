"""Travaux longs exécutés hors de l'interface pour qu'elle reste réactive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..detectors.ner import NerDetector
from ..dictionary import CompanyDictionary
from ..pipeline import collect, write
from ..session import AnonymizationSession, SessionConfig

_NER: NerDetector | None = None


def get_ner(labels: tuple[str, ...]) -> NerDetector:
    """Le modèle de langue est chargé une seule fois (quelques secondes)."""
    global _NER
    if _NER is None:
        _NER = NerDetector(labels=labels)
    _NER.labels = set(labels)
    return _NER


class _Worker(QObject):
    progress = Signal(str, int, int)
    failed = Signal(str)

    def _report(self, message: str, done: int, total: int) -> None:
        self.progress.emit(message, done, total)


class AnalyzeWorker(_Worker):
    finished = Signal(object, object)  # session, rapports

    def __init__(self, paths: list[Path], dictionary: CompanyDictionary, mask_places: bool):
        super().__init__()
        self.paths, self.dictionary, self.mask_places = paths, dictionary, mask_places

    def run(self) -> None:
        try:
            labels = ("PER", "ORG", "LOC") if self.mask_places else ("PER", "ORG")
            self.progress.emit("Chargement du modèle de langue…", 0, len(self.paths))
            ner = get_ner(labels)
            config = SessionConfig(ner_labels=labels)
            session = AnonymizationSession(config, self.dictionary, ner=ner)
            reports = collect(self.paths, session, self._report)
            self.finished.emit(session, reports)
        except Exception as exc:  # affiché à l'utilisateur
            self.failed.emit(str(exc))


class WriteWorker(_Worker):
    finished = Signal(object)  # rapports

    def __init__(self, session: AnonymizationSession, reports, out_dir: Path):
        super().__init__()
        self.session, self.reports, self.out_dir = session, reports, out_dir

    def run(self) -> None:
        try:
            self.finished.emit(write(self.reports, self.session, self.out_dir, self._report))
        except Exception as exc:
            self.failed.emit(str(exc))


def start(worker: _Worker, parent: QObject) -> QThread:
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for signal in (worker.finished, worker.failed):
        signal.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread._worker = worker  # garde une référence
    thread.start()
    return thread
