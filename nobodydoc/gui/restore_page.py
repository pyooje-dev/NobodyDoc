"""Onglet « Restaurer les vrais noms »."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from ..formats import SUPPORTED_EXTENSIONS
from ..pipeline import restore_files
from ..vault import MappingTable, TableStore

RETENTION_CHOICES = [(30, "après 30 jours"), (90, "après 90 jours"), (365, "après 1 an"), (0, "jamais")]
FILE_FILTER = "Documents (" + " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS) + ")"


def _label(text: str, name: str | None = None, wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


class RestorePage(QWidget):
    tables_changed = Signal()

    def __init__(self, store: TableStore, prefs: dict):
        super().__init__()
        self.store = store
        self.prefs = prefs
        self.tables: list[MappingTable] = []
        self.setAcceptDrops(True)

        self.table_combo = QComboBox()
        self.table_combo.setMinimumWidth(420)
        self.table_combo.currentIndexChanged.connect(self._refresh_hint)
        delete = QPushButton("Supprimer cette table")
        delete.clicked.connect(self._delete_current)
        self.retention = QComboBox()
        for days, text in RETENTION_CHOICES:
            self.retention.addItem(text, days)
        self.retention.setCurrentIndex(
            max(0, self.retention.findData(int(prefs.get("conservation_jours", 90)))))
        self.retention.currentIndexChanged.connect(self._retention_changed)
        self.hint = _label("", "subtitle")

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Collez ici la réponse de l'IA ou du prestataire, avec ses jetons [PERSONNE_1], [CLIENT_2]…")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Le texte avec les vraies valeurs apparaîtra ici.")
        restore = QPushButton("Restaurer  →")
        restore.setObjectName("primary")
        restore.clicked.connect(self.restore_text)
        copy = QPushButton("Copier le résultat")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.output.toPlainText()))
        self.text_status = _label("", "subtitle")

        files_btn = QPushButton("Restaurer des fichiers…")
        files_btn.clicked.connect(self._choose_files)

        table_row = QHBoxLayout()
        table_row.addWidget(_label("<b>Table :</b>", wrap=False))
        table_row.addWidget(self.table_combo, 1)
        table_row.addWidget(delete)

        retention_row = QHBoxLayout()
        retention_row.addWidget(_label("Supprimer automatiquement les tables", "subtitle", wrap=False))
        retention_row.addWidget(self.retention)
        retention_row.addStretch()

        texts = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(_label("Texte reçu", "sectionTitle"))
        left.addWidget(self.input)
        right = QVBoxLayout()
        right.addWidget(_label("Texte restauré", "sectionTitle"))
        right.addWidget(self.output)
        texts.addLayout(left)
        texts.addLayout(right)

        text_actions = QHBoxLayout()
        text_actions.addWidget(self.text_status, 1)
        text_actions.addWidget(restore)
        text_actions.addWidget(copy)

        files_card = QFrame()
        files_card.setObjectName("card")
        files_lay = QHBoxLayout(files_card)
        files_lay.addWidget(_label(
            "<b>Un document renvoyé ?</b> Glissez-le sur cette page ou choisissez-le : une copie "
            "« _restaure » est créée à côté, avec les vraies valeurs.", wrap=True), 1)
        files_lay.addWidget(files_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        lay.addWidget(_label("Restaurer les vrais noms", "title"))
        lay.addWidget(_label(
            "Quand l'IA ou le prestataire vous répond avec des jetons comme [PERSONNE_1], remettez les "
            "vraies valeurs grâce à la table enregistrée lors de l'anonymisation. Les tables sont "
            "chiffrées et ne peuvent être lues que par votre compte Windows, sur ce poste.", "subtitle"))
        lay.addLayout(table_row)
        lay.addWidget(self.hint)
        lay.addLayout(texts, 1)
        lay.addLayout(text_actions)
        lay.addWidget(files_card)
        lay.addLayout(retention_row)

    # ------------------------------------------------------------------ tables

    def reload(self) -> None:
        days = self.retention.currentData()
        if days:
            self.store.delete_older_than(days)
        current = self.current_table()
        current_path = current.path if current else None
        self.tables = self.store.list()
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        for table in self.tables:
            self.table_combo.addItem(table.label)
        if not self.tables:
            self.table_combo.addItem("Aucune table : anonymisez d'abord des documents")
        for i, table in enumerate(self.tables):
            if table.path == current_path:
                self.table_combo.setCurrentIndex(i)
        self.table_combo.blockSignals(False)
        self._refresh_hint()

    def current_table(self) -> MappingTable | None:
        i = self.table_combo.currentIndex()
        return self.tables[i] if 0 <= i < len(self.tables) else None

    def _refresh_hint(self) -> None:
        table = self.current_table()
        if table is None:
            self.hint.setText("")
            return
        files = ", ".join(Path(f).name for f in table.files)
        self.hint.setText(f"Fichiers anonymisés avec cette table : {files}")

    def _delete_current(self) -> None:
        table = self.current_table()
        if table is None:
            return
        if QMessageBox.question(
            self, "Supprimer la table",
            "Les documents anonymisés avec cette table ne pourront plus être restaurés. Supprimer ?",
        ) != QMessageBox.Yes:
            return
        self.store.delete(table)
        self.reload()

    def _retention_changed(self) -> None:
        self.prefs["conservation_jours"] = self.retention.currentData()
        settings.save_prefs(self.prefs)
        self.reload()

    # ------------------------------------------------------------------ restauration

    def restore_text(self) -> None:
        table = self.current_table()
        if table is None:
            QMessageBox.information(self, "Aucune table", "Anonymisez d'abord des documents.")
            return
        text = self.input.toPlainText()
        result = table.apply(text)
        self.output.setPlainText(result.text)
        unknown = table.unknown_tokens(text)
        status = f"{len(result.replacements)} jeton(s) remplacé(s)."
        if unknown:
            status += (f" ⚠ {len(unknown)} jeton(s) absent(s) de cette table ({', '.join(unknown[:5])}) : "
                       "avez-vous choisi la bonne table ?")
        self.text_status.setText(status)

    def restore_paths(self, paths: list[Path]) -> list:
        table = self.current_table()
        if table is None:
            QMessageBox.information(self, "Aucune table", "Anonymisez d'abord des documents.")
            return []
        paths = [p for p in paths if p.is_file()]
        reports = restore_files(paths, table)
        lines = []
        for r in reports:
            name = Path(r.source).name
            if r.error:
                lines.append(f"✗ {name} : {r.error}")
            else:
                lines.append(f"✓ {name} → {Path(r.output).name} ({r.total} valeur(s) restaurée(s))")
                lines += [f"   ⚠ {w}" for w in r.warnings]
        if reports:
            box = QMessageBox(QMessageBox.Information, "Restauration terminée", "\n".join(lines), parent=self)
            open_btn = box.addButton("Ouvrir le dossier", QMessageBox.AcceptRole)
            box.addButton("Fermer", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(reports[0].source).parent)))
        return reports

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Fichiers à restaurer", "", FILE_FILTER)
        if paths:
            self.restore_paths([Path(p) for p in paths])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.restore_paths(paths)
