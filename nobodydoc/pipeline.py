"""Traitement d'un lot de fichiers : collecte sur tous, puis écriture."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from .formats import SUPPORTED_EXTENSIONS, handler_for
from .formats.base import FileReport
from .session import AnonymizationSession

ProgressCallback = Callable[[str, int, int], None]
OUTPUT_SUFFIX = "_anonymise"


def output_path(source: Path, out_dir: Path) -> Path:
    handler = handler_for(source.suffix)
    ext = source.suffix
    if handler is not None and hasattr(handler, "output_extension"):
        ext = handler.output_extension(ext)
    return out_dir / f"{source.stem}{OUTPUT_SUFFIX}{ext}"


def collect(paths: Iterable[Path], session: AnonymizationSession,
            progress: ProgressCallback | None = None) -> list[FileReport]:
    """Passe 1 : lit tous les fichiers et détecte les données sensibles."""
    paths = list(paths)
    reports = []
    for i, path in enumerate(paths):
        if progress:
            progress(f"Analyse de {path.name}", i, len(paths))
        report = FileReport(str(path))
        handler = handler_for(path.suffix)
        if handler is None:
            report.error = f"Format non pris en charge ({path.suffix}). Formats acceptés : " + ", ".join(SUPPORTED_EXTENSIONS)
        else:
            try:
                session.collect(handler.iter_texts(path.read_bytes()))
            except Exception as exc:  # fichier corrompu, protégé par mot de passe...
                report.error = f"Lecture impossible : {exc}"
        reports.append(report)
    return reports


def write(reports: list[FileReport], session: AnonymizationSession, out_dir: Path,
          progress: ProgressCallback | None = None) -> list[FileReport]:
    """Passe 2 : écrit les copies anonymisées (les originaux ne sont jamais modifiés)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, report in enumerate(reports):
        if report.error:
            continue
        path = Path(report.source)
        if progress:
            progress(f"Anonymisation de {path.name}", i, len(reports))
        target = output_path(path, out_dir)
        try:
            data = handler_for(path.suffix).anonymize(path.read_bytes(), session, report)
            target.write_bytes(data)
            report.output = str(target)
            report.finalize()
        except Exception as exc:
            report.error = f"Écriture impossible : {exc}"
    return reports


def anonymize_files(paths: Iterable[Path], session: AnonymizationSession, out_dir: Path,
                    progress: ProgressCallback | None = None) -> list[FileReport]:
    reports = collect(paths, session, progress)
    return write(reports, session, out_dir, progress)


# ----------------------------------------------------------------------------- restauration

RESTORED_SUFFIX = "_restaure"


def restored_path(source: Path, out_dir: Path | None = None) -> Path:
    stem = source.stem
    if stem.endswith(OUTPUT_SUFFIX):
        stem = stem[: -len(OUTPUT_SUFFIX)]
    handler = handler_for(source.suffix)
    ext = source.suffix
    if handler is not None and hasattr(handler, "output_extension"):
        ext = handler.output_extension(ext)
    return (out_dir or source.parent) / f"{stem}{RESTORED_SUFFIX}{ext}"


def restore_files(paths: Iterable[Path], table, out_dir: Path | None = None,
                  progress: ProgressCallback | None = None) -> list[FileReport]:
    """Remet les vraies valeurs dans des fichiers contenant des jetons.

    ``table`` est une ``vault.MappingTable``. Les copies sont écrites à côté des
    fichiers d'origine (ou dans ``out_dir``) avec le suffixe « _restaure ».
    """
    paths = list(paths)
    reports = []
    for i, path in enumerate(paths):
        if progress:
            progress(f"Restauration de {path.name}", i, len(paths))
        report = FileReport(str(path))
        handler = handler_for(path.suffix)
        if handler is None:
            report.error = f"Format non pris en charge ({path.suffix})."
            reports.append(report)
            continue
        try:
            data = path.read_bytes()
            unknown = set()
            for text in handler.iter_texts(data):
                unknown.update(table.unknown_tokens(text))
            target = restored_path(path, out_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(handler.anonymize(data, table, report))
            report.output = str(target)
            if unknown:
                report.warn(
                    "Jetons absents de cette table (mauvaise table ?) : " + ", ".join(sorted(unknown)[:10])
                )
        except Exception as exc:
            report.error = f"Restauration impossible : {exc}"
        reports.append(report)
    return reports
