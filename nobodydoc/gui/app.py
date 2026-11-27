"""Fenêtre principale : fichiers → vérification → résultat."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, settings
from ..dictionary import CompanyDictionary
from ..entities import CATEGORY_LABELS, normalize_category
from ..formats import SUPPORTED_EXTENSIONS, file_extension
from ..formats.code import CodeHandler
from ..session import AnonymizationSession
from . import style
from ..vault import TableStore
from .dictionary_dialog import DictionaryDialog
from .restore_page import RestorePage
from .workers import AnalyzeWorker, WriteWorker, start

FILE_FILTER = (
    "Documents pris en charge (" + " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS) + ");;"
    "Word (*.docx *.docm);;Excel (*.xlsx *.xlsm);;PowerPoint (*.pptx *.pptm);;"
    "Mails (*.msg *.eml);;Texte (*.txt *.csv *.md *.json);;"
    "Code et configuration (" + " ".join(f"*{e}" for e in CodeHandler.extensions) + ")"
)
# Dossiers ignorés quand on dépose un projet de code entier.
SKIPPED_DIRS = {"node_modules", "venv", "__pycache__", "dist", "build", "target", "bin", "obj"}
SOURCE_LABELS = {
    "dictionnaire": "Dictionnaire",
    "regle": "Règle",
    "ner": "Modèle (à vérifier)",
    "connu": "Déjà repéré",
    "manuel": "Ajout manuel",
    "metadonnee": "Auteur",
    "colonne": "Colonne de noms (Excel)",
}
RESOURCES = Path(__file__).parent / "resources"
DEFAULT_CATEGORIES = ["PERSONNE", "ORGANISATION", "CLIENT", "PRODUIT", "PROJET", "DEPARTEMENT", "LIEU", "DIVERS"]
OLD_FORMATS = {".doc": "Word", ".xls": "Excel", ".ppt": "PowerPoint"}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())


def label(text: str, name: str | None = None, wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, name: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def expand_paths(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Développe les dossiers ; renvoie (fichiers pris en charge, fichiers refusés)."""
    accepted, rejected = [], []
    for path in paths:
        if path.is_dir():
            candidates = sorted(
                p for p in path.rglob("*")
                if p.is_file() and not any(
                    part.startswith(".") or part in SKIPPED_DIRS for part in p.relative_to(path).parts[:-1])
            )
        else:
            candidates = [path]
        for p in candidates:
            if p.name.startswith("~$"):  # fichiers temporaires d'Office
                continue
            (accepted if file_extension(p).lower() in SUPPORTED_EXTENSIONS else rejected).append(p)
    return accepted, rejected


# ============================================================================ page 1


class DropZone(QFrame):
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(170)
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(QStyle.SP_FileDialogNewFolder).pixmap(40, 40))
        icon.setAlignment(Qt.AlignCenter)
        main = label("<b>Glissez vos fichiers ici</b> ou cliquez pour les choisir", wrap=False)
        main.setAlignment(Qt.AlignCenter)
        main.setStyleSheet("font-size: 12pt; background: transparent;")
        sub = label("Word, Excel, PowerPoint, mails Outlook (.msg, .eml), texte, SQL et code. Dossiers acceptés.", "subtitle")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.addStretch()
        lay.addWidget(icon)
        lay.addWidget(main)
        lay.addWidget(sub)
        lay.addStretch()

    def _set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, event):
        self._set_hover(False)

    def dropEvent(self, event):
        self._set_hover(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class FilesPage(QWidget):
    analyze_requested = Signal()
    dictionary_requested = Signal()

    def __init__(self):
        super().__init__()
        self.files: list[Path] = []

        self.drop = DropZone()
        self.drop.files_dropped.connect(self.add_paths)
        self.drop.clicked.connect(self.choose_files)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(20, 20))
        self.count_label = label("", "sectionTitle", wrap=False)
        remove = button("Retirer la sélection")
        remove.clicked.connect(self.remove_selected)
        clear = button("Tout retirer")
        clear.clicked.connect(self.clear)

        self.places = QCheckBox("Masquer aussi les villes et les pays")
        self.dict_button = button("", "link")
        self.dict_button.clicked.connect(self.dictionary_requested)

        self.analyze = button("Analyser les fichiers  →", "primary")
        self.analyze.clicked.connect(self.analyze_requested)

        files_header = QHBoxLayout()
        files_header.addWidget(self.count_label)
        files_header.addStretch()
        files_header.addWidget(remove)
        files_header.addWidget(clear)

        options = QHBoxLayout()
        options.addWidget(self.places)
        options.addSpacing(20)
        options.addWidget(self.dict_button)
        options.addStretch()

        footer = QHBoxLayout()
        footer.addWidget(label(
            "🔒 Tout se passe sur cet ordinateur : aucun fichier n'est envoyé sur Internet. "
            "Les originaux ne sont jamais modifiés.", "subtitle"), 1)
        footer.addWidget(self.analyze)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(12)
        lay.addWidget(label("Anonymiser des documents", "title"))
        lay.addWidget(label(
            "Les noms, coordonnées, IBAN, adresses et les termes de votre entreprise sont remplacés "
            "par des jetons comme [PERSONNE_1] ou [CLIENT_2], identiques dans tous les fichiers.",
            "subtitle"))
        lay.addWidget(self.drop)
        lay.addLayout(files_header)
        lay.addWidget(self.list, 1)
        lay.addLayout(options)
        lay.addLayout(footer)
        self._refresh()

    def set_dictionary_size(self, terms: int, exclusions: int) -> None:
        self.dict_button.setText(
            f"📖 Dictionnaire de l'entreprise : {terms} terme(s) à masquer, {exclusions} exclusion(s)  ›"
        )

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", "", FILE_FILTER)
        self.add_paths([Path(p) for p in paths])

    def add_paths(self, paths: list[Path]) -> None:
        accepted, rejected = expand_paths(paths)
        known = {p.resolve() for p in self.files}
        for path in accepted:
            if path.resolve() not in known and path.stem.endswith("_anonymise") is False:
                self.files.append(path)
                known.add(path.resolve())
        self._refresh()
        if rejected:
            old = [p for p in rejected if p.suffix.lower() in OLD_FORMATS]
            message = f"{len(rejected)} fichier(s) ignoré(s), format non pris en charge :\n"
            message += "\n".join(f"• {p.name}" for p in rejected[:8])
            if len(rejected) > 8:
                message += "\n…"
            if old:
                message += (
                    "\n\nLes anciens formats (.doc, .xls, .ppt) doivent d'abord être réenregistrés "
                    "au format récent depuis Word, Excel ou PowerPoint (Fichier > Enregistrer sous)."
                )
            QMessageBox.information(self, "Fichiers ignorés", message)

    def remove_selected(self) -> None:
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        for row in rows:
            del self.files[row]
        self._refresh()

    def clear(self) -> None:
        self.files.clear()
        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        provider = self.style()
        for path in self.files:
            item = QListWidgetItem(provider.standardIcon(QStyle.SP_FileIcon), f"{path.name}    —    {path.parent}")
            item.setToolTip(str(path))
            self.list.addItem(item)
        n = len(self.files)
        self.count_label.setText(f"{n} fichier(s) à anonymiser" if n else "Aucun fichier pour l'instant")
        self.analyze.setEnabled(n > 0)


# ============================================================================ page 2


class ProgressPage(QWidget):
    def __init__(self):
        super().__init__()
        self.title = label("", "title")
        self.message = label("", "subtitle")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(80, 0, 80, 0)
        lay.addStretch(2)
        lay.addWidget(self.title)
        lay.addWidget(self.message)
        lay.addSpacing(10)
        lay.addWidget(self.bar)
        lay.addStretch(3)

    def begin(self, title: str) -> None:
        self.title.setText(title)
        self.message.setText("")
        self.bar.setRange(0, 0)

    def update_progress(self, message: str, done: int, total: int) -> None:
        self.message.setText(message)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)


# ============================================================================ page 3

COL_CHECK, COL_CATEGORY, COL_VALUE, COL_TOKEN, COL_COUNT, COL_SOURCE = range(6)


class ReviewPage(QWidget):
    back_requested = Signal()
    anonymize_requested = Signal()
    dictionary_changed = Signal()

    def __init__(self):
        super().__init__()
        self.session: AnonymizationSession | None = None
        self.dictionary: CompanyDictionary | None = None
        self.out_dir: Path | None = None
        self.file_count = 0
        self._filling = False

        self.summary = label("", "subtitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self._apply_filter)
        self.only_check = QCheckBox("Seulement « à vérifier »")
        self.only_check.toggled.connect(self._apply_filter)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Masquer", "Catégorie", "Valeur trouvée", "Remplacée par", "Fois", "Origine"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemChanged.connect(self._item_changed)
        header = self.table.horizontalHeader()
        for col, mode in ((COL_CHECK, QHeaderView.ResizeToContents), (COL_CATEGORY, QHeaderView.ResizeToContents),
                          (COL_VALUE, QHeaderView.Stretch), (COL_TOKEN, QHeaderView.ResizeToContents),
                          (COL_COUNT, QHeaderView.ResizeToContents), (COL_SOURCE, QHeaderView.ResizeToContents)):
            header.setSectionResizeMode(col, mode)

        check_all = button("Tout cocher")
        check_all.clicked.connect(lambda: self._check_visible(True))
        uncheck_all = button("Tout décocher")
        uncheck_all.clicked.connect(lambda: self._check_visible(False))
        never = button("Ne jamais masquer…")
        never.setToolTip("Ajoute les lignes sélectionnées aux exclusions du dictionnaire")
        never.clicked.connect(self._never_mask_selected)
        always = button("Toujours masquer…")
        always.setToolTip("Ajoute les lignes sélectionnées au dictionnaire de l'entreprise")
        always.clicked.connect(self._always_mask_selected)

        # Ajout d'un terme oublié
        self.new_term = QLineEdit()
        self.new_term.setPlaceholderText("Un nom, un code projet, un acronyme… oublié ?")
        self.new_term.returnPressed.connect(self._add_term)
        self.new_category = QComboBox()
        self.new_category.setEditable(True)
        self.remember = QCheckBox("Mémoriser dans le dictionnaire")
        self.remember.setChecked(True)
        add = button("Ajouter")
        add.clicked.connect(self._add_term)

        self.keep_table = QCheckBox("Garder une table chiffrée pour restaurer les vrais noms dans les réponses")
        self.keep_table.setChecked(True)
        self.out_label = label("", "subtitle", wrap=False)
        change_out = button("Changer…", "link")
        change_out.clicked.connect(self._choose_out_dir)
        back = button("←  Retour")
        back.clicked.connect(self.back_requested)
        self.go = button("", "primary")
        self.go.clicked.connect(self.anonymize_requested)

        filters = QHBoxLayout()
        filters.addWidget(self.search, 2)
        filters.addWidget(self.category_filter, 1)
        filters.addWidget(self.only_check)

        actions = QHBoxLayout()
        for w in (check_all, uncheck_all, never, always):
            actions.addWidget(w)
        actions.addStretch()

        add_card = QFrame()
        add_card.setObjectName("card")
        add_lay = QHBoxLayout(add_card)
        add_lay.addWidget(label("<b>Ajouter :</b>", wrap=False))
        add_lay.addWidget(self.new_term, 3)
        add_lay.addWidget(self.new_category, 1)
        add_lay.addWidget(self.remember)
        add_lay.addWidget(add)

        out_row = QHBoxLayout()
        out_row.addWidget(self.out_label)
        out_row.addWidget(change_out)
        out_row.addStretch()
        out_row.addWidget(back)
        out_row.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        lay.addWidget(label("Vérifiez ce qui va être masqué", "title"))
        lay.addWidget(self.summary)
        lay.addLayout(filters)
        lay.addWidget(self.table, 1)
        lay.addLayout(actions)
        lay.addWidget(add_card)
        lay.addWidget(self.keep_table)
        lay.addLayout(out_row)

    # ------------------------------------------------------------------ remplissage

    def load(self, session: AnonymizationSession, dictionary: CompanyDictionary, file_count: int, out_dir: Path) -> None:
        self.session, self.dictionary, self.file_count = session, dictionary, file_count
        self.set_out_dir(out_dir)
        self.go.setText(f"Anonymiser {file_count} fichier(s)  →")
        self._fill()

    def _fill(self) -> None:
        self._filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        entities = [e for e in self.session.entity_list() if e.sources - {"metadonnee"}]
        for entity in entities:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if entity.enabled else Qt.Unchecked)
            check.setData(Qt.UserRole, entity.placeholder)
            values = sorted(entity.values, key=len, reverse=True)
            value_item = QTableWidgetItem(values[0] + (f"   (+ {', '.join(values[1:])})" if len(values) > 1 else ""))
            value_item.setToolTip("\n".join(values))
            count = QTableWidgetItem()
            count.setData(Qt.DisplayRole, entity.occurrences)
            source = self._source_label(entity.sources)
            source_item = QTableWidgetItem(source)
            if "à vérifier" in source:
                source_item.setForeground(QColor(style.WARNING))
            for col, item in ((COL_CHECK, check), (COL_CATEGORY, QTableWidgetItem(category_label(entity.category))),
                              (COL_VALUE, value_item), (COL_TOKEN, QTableWidgetItem(entity.placeholder)),
                              (COL_COUNT, count), (COL_SOURCE, source_item)):
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_CATEGORY)
        self._filling = False

        categories = sorted({e.category for e in entities})
        self.category_filter.blockSignals(True)
        current = self.category_filter.currentData()
        self.category_filter.clear()
        self.category_filter.addItem("Toutes les catégories", None)
        for cat in categories:
            self.category_filter.addItem(category_label(cat), cat)
        index = self.category_filter.findData(current)
        self.category_filter.setCurrentIndex(max(index, 0))
        self.category_filter.blockSignals(False)

        self.new_category.clear()
        for cat in dict.fromkeys(DEFAULT_CATEGORIES + self.dictionary.categories() + categories):
            self.new_category.addItem(cat)
        self._apply_filter()
        self._update_summary()

    @staticmethod
    def _source_label(sources: set[str]) -> str:
        for key in ("manuel", "dictionnaire", "regle", "colonne"):
            if key in sources:
                return SOURCE_LABELS[key]
        return SOURCE_LABELS["ner"]

    def _update_summary(self) -> None:
        total = self.table.rowCount()
        checked = sum(1 for r in range(total) if self.table.item(r, COL_CHECK).checkState() == Qt.Checked)
        to_check = sum(1 for r in range(total) if "à vérifier" in self.table.item(r, COL_SOURCE).text())
        text = (f"{total} élément(s) trouvé(s) dans {self.file_count} fichier(s), {checked} seront masqués. "
                "Décochez ce qui ne doit pas l'être, ajoutez ce qui manque.")
        if to_check:
            text += f" {to_check} élément(s) proposés par le modèle de langue sont à vérifier en priorité."
        self.summary.setText(text)

    # ------------------------------------------------------------------ interactions

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        category = self.category_filter.currentData()
        only = self.only_check.isChecked()
        for row in range(self.table.rowCount()):
            placeholder = self.table.item(row, COL_CHECK).data(Qt.UserRole)
            entity = self.session.entities[placeholder] if self.session else None
            visible = True
            if category and entity and entity.category != category:
                visible = False
            if only and "à vérifier" not in self.table.item(row, COL_SOURCE).text():
                visible = False
            if needle and needle not in self.table.item(row, COL_VALUE).text().casefold() \
                    and needle not in placeholder.casefold():
                visible = False
            self.table.setRowHidden(row, not visible)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != COL_CHECK or self.session is None:
            return
        self.session.set_enabled(item.data(Qt.UserRole), item.checkState() == Qt.Checked)
        self._update_summary()

    def _check_visible(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, COL_CHECK).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _selected_entities(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.session.entities[self.table.item(r, COL_CHECK).data(Qt.UserRole)] for r in rows]

    def _never_mask_selected(self) -> None:
        entities = self._selected_entities()
        if not entities:
            QMessageBox.information(self, "Aucune sélection", "Sélectionnez d'abord une ou plusieurs lignes.")
            return
        names = ", ".join(sorted({v for e in entities for v in e.values}))
        if QMessageBox.question(
            self, "Ne jamais masquer",
            f"Ces mots ne seront plus jamais masqués, dans ce lot et les suivants :\n\n{names}\n\nContinuer ?",
        ) != QMessageBox.Yes:
            return
        for entity in entities:
            entity.enabled = False
            for value in entity.values:
                self.dictionary.add_exclusion(value)
        self.dictionary_changed.emit()
        self._fill()

    def _always_mask_selected(self) -> None:
        entities = self._selected_entities()
        if not entities:
            QMessageBox.information(self, "Aucune sélection", "Sélectionnez d'abord une ou plusieurs lignes.")
            return
        for entity in entities:
            values = sorted(entity.values, key=len, reverse=True)
            self.dictionary.add_term(values[0], entity.category, values[1:])
            entity.enabled = True
        self.dictionary_changed.emit()
        self._fill()
        QMessageBox.information(self, "Dictionnaire", f"{len(entities)} terme(s) ajouté(s) au dictionnaire.")

    def _add_term(self) -> None:
        value = self.new_term.text().strip()
        if not value or self.session is None:
            return
        category = normalize_category(self.new_category.currentText() or "DIVERS")
        self.dictionary.remove_exclusion(value)
        entity = self.session.add_manual(value, category)
        if entity is None:
            return
        if self.remember.isChecked():
            self.dictionary.add_term(value, category)
            self.dictionary_changed.emit()
        self.new_term.clear()
        self._fill()
        if entity.occurrences == 0:
            QMessageBox.information(
                self, "Terme ajouté",
                f"« {value} » n'apparaît pas tel quel dans les fichiers, mais il sera masqué s'il s'y trouve.")

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(QAction("Ne jamais masquer", self, triggered=self._never_mask_selected))
        menu.addAction(QAction("Toujours masquer (dictionnaire)", self, triggered=self._always_mask_selected))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def set_out_dir(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_label.setText(f"📁 Copies enregistrées dans : <b>{out_dir}</b>")

    def _choose_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Dossier des copies anonymisées", str(self.out_dir or ""))
        if path:
            self.set_out_dir(Path(path))


# ============================================================================ page 4


class ResultPage(QWidget):
    restart_requested = Signal()

    def __init__(self):
        super().__init__()
        self.out_dir: Path | None = None
        self.title = label("", "title")
        self.summary = label("", "subtitle")
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        reminder = label(
            "⚠ Relisez les copies avant de les envoyer : l'outil ne lit pas le texte des images "
            "et peut manquer des cas inhabituels.", "subtitle")
        open_dir = button("Ouvrir le dossier", "primary")
        open_dir.clicked.connect(self._open_dir)
        restart = button("Anonymiser d'autres fichiers")
        restart.clicked.connect(self.restart_requested)
        row = QHBoxLayout()
        row.addWidget(reminder, 1)
        row.addWidget(restart)
        row.addWidget(open_dir)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        lay.addWidget(self.title)
        lay.addWidget(self.summary)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)

    def show_reports(self, reports, out_dir: Path, table_saved: bool = False) -> None:
        self.out_dir = out_dir
        ok = [r for r in reports if not r.error]
        errors = [r for r in reports if r.error]
        total = sum(r.total for r in ok)
        self.title.setText("✓ C'est fait" if not errors else "Terminé, avec des erreurs")
        summary = (f"{len(ok)} fichier(s) anonymisé(s), {total} remplacement(s). "
                   f"Les copies sont dans {out_dir}.")
        if table_saved:
            summary += (" La table de correspondance est enregistrée (chiffrée) : l'onglet "
                        "« Restaurer les vrais noms » remettra les vraies valeurs dans les réponses.")
        self.summary.setText(summary)
        self.list.clear()
        for report in reports:
            name = Path(report.source).name
            if report.error:
                item = QListWidgetItem(f"✗  {name}\n     {report.error}")
                item.setForeground(QColor(style.ERROR))
                self.list.addItem(item)
                continue
            detail = ", ".join(f"{category_label(c).lower()} : {n}" for c, n in sorted(report.replacements.items()))
            text = f"✓  {name}  →  {Path(report.output).name}\n     {report.total} remplacement(s)"
            if detail:
                text += f" ({detail})"
            if report.metadata:
                text += f", {report.metadata} métadonnée(s) nettoyée(s)"
            item = QListWidgetItem(text)
            item.setForeground(QColor(style.SUCCESS))
            self.list.addItem(item)
            for warning in report.warnings:
                w = QListWidgetItem(f"     ⚠ {warning}")
                w.setForeground(QColor(style.WARNING))
                self.list.addItem(w)

    def _open_dir(self) -> None:
        if self.out_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))


# ============================================================================ aide

HELP_ICONS = {"Anonymiser": "1", "Remettre": "2", "Le dictionnaire": "3", "Ce qui": "✓", "Bon à savoir": "i"}


def split_guide(markdown: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Découpe le guide en (titre, introduction, [(titre de section, contenu)])."""
    title, intro, sections = "", [], []
    current: list[str] | None = None
    for line in markdown.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = []
            sections.append((line[3:].strip(), current))
        elif current is None:
            intro.append(line)
        else:
            current.append(line)
    return title, "\n".join(intro).strip(), [(t, "\n".join(body).strip()) for t, body in sections]


class HelpPage(QScrollArea):
    """Guide d'utilisation présenté en cartes, une par section."""

    def __init__(self, guide: Path):
        super().__init__()
        self.setObjectName("help")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        try:
            title, intro, sections = split_guide(guide.read_text(encoding="utf-8"))
        except OSError:
            title, intro, sections = "Guide introuvable", "", []

        content = QWidget()
        content.setObjectName("helpContent")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(label(title, "title"))
        if intro:
            lay.addWidget(self._markdown(intro, "subtitle"))
        self.cards: list[QFrame] = []
        for section_title, body in sections:
            card = QFrame()
            card.setObjectName("card")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(20, 16, 20, 16)
            card_lay.setSpacing(8)
            badge = next((v for k, v in HELP_ICONS.items() if section_title.startswith(k)), "•")
            header = label(f"{badge}  ·  {section_title}" if badge.isdigit() else section_title, "helpTitle")
            card_lay.addWidget(header)
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {style.BORDER};")
            card_lay.addWidget(line)
            card_lay.addWidget(self._markdown(body, "helpBody"))
            lay.addWidget(card)
            self.cards.append(card)
        lay.addStretch()
        self.setWidget(content)

    @staticmethod
    def _markdown(text: str, name: str) -> QLabel:
        lab = QLabel()
        lab.setObjectName(name)
        lab.setTextFormat(Qt.MarkdownText)
        lab.setText(text)
        lab.setWordWrap(True)
        lab.setOpenExternalLinks(True)
        lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
        return lab


# ============================================================================ fenêtre


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NobodyDoc {__version__} — anonymisation locale")
        self.resize(1000, 700)
        self.prefs = settings.load_prefs()
        self.dictionary = self._load_dictionary()
        self.session: AnonymizationSession | None = None
        self.reports = None
        self._thread = None

        self.files_page = FilesPage()
        self.progress_page = ProgressPage()
        self.review_page = ReviewPage()
        self.result_page = ResultPage()
        self.stack = QStackedWidget()
        for page in (self.files_page, self.progress_page, self.review_page, self.result_page):
            self.stack.addWidget(page)
        self.store = TableStore()
        self.restore_page = RestorePage(self.store, self.prefs)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.stack, "Anonymiser")
        self.tabs.addTab(self.restore_page, "Restaurer les vrais noms")
        self.tabs.addTab(self._help_page(), "Aide")
        self.tabs.currentChanged.connect(
            lambda i: self.restore_page.reload() if self.tabs.widget(i) is self.restore_page else None)
        self.setCentralWidget(self.tabs)

        self.files_page.places.setChecked(bool(self.prefs.get("masquer_lieux", False)))
        self.files_page.analyze_requested.connect(self.analyze)
        self.files_page.dictionary_requested.connect(self.edit_dictionary)
        self.review_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.files_page))
        self.review_page.anonymize_requested.connect(self.write)
        self.review_page.dictionary_changed.connect(self._save_dictionary)
        self.result_page.restart_requested.connect(self.restart)
        self.review_page.keep_table.setChecked(bool(self.prefs.get("garder_table", True)))
        self._refresh_dictionary_label()

    @staticmethod
    def _help_page() -> QWidget:
        return HelpPage(RESOURCES / "guide.md")

    # ------------------------------------------------------------------ dictionnaire

    def _load_dictionary(self) -> CompanyDictionary:
        path = settings.dictionary_path()
        if path.exists():
            try:
                return CompanyDictionary.load(path)
            except Exception as exc:
                QMessageBox.warning(self, "Dictionnaire illisible",
                                    f"Le dictionnaire {path} n'a pas pu être lu ({exc}). Un dictionnaire vide est utilisé.")
        return CompanyDictionary()

    def _save_dictionary(self) -> None:
        try:
            self.dictionary.save(settings.dictionary_path())
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
        self._refresh_dictionary_label()

    def _refresh_dictionary_label(self) -> None:
        self.files_page.set_dictionary_size(len(self.dictionary.terms), len(self.dictionary.exclusion_list))

    def edit_dictionary(self) -> None:
        dialog = DictionaryDialog(self.dictionary, self)
        if dialog.exec():
            new = dialog.result_dictionary()
            self.dictionary.replace_all(new.terms, new.exclusion_list)
            self._save_dictionary()

    # ------------------------------------------------------------------ étapes

    def analyze(self) -> None:
        files = list(self.files_page.files)
        if not files:
            return
        mask_places = self.files_page.places.isChecked()
        self.prefs["masquer_lieux"] = mask_places
        settings.save_prefs(self.prefs)
        self.progress_page.begin("Analyse en cours…")
        self.stack.setCurrentWidget(self.progress_page)
        worker = AnalyzeWorker(files, self.dictionary, mask_places)
        worker.progress.connect(self.progress_page.update_progress)
        worker.finished.connect(self._analyzed)
        worker.failed.connect(self._failed)
        self._thread = start(worker, self)

    def _analyzed(self, session: AnonymizationSession, reports) -> None:
        self.session, self.reports = session, reports
        errors = [r for r in reports if r.error]
        if errors:
            QMessageBox.warning(
                self, "Certains fichiers n'ont pas pu être lus",
                "\n".join(f"• {Path(r.source).name} : {r.error}" for r in errors)
                + "\n\nUn fichier protégé par mot de passe doit être déverrouillé avant l'anonymisation.")
        readable = len(reports) - len(errors)
        if readable == 0:
            self.stack.setCurrentWidget(self.files_page)
            return
        if session.ner is not None and not session.ner.available:
            QMessageBox.warning(self, "Modèle de langue absent",
                                "Les noms de personnes et d'entreprises ne seront repérés que via le dictionnaire.")
        first = Path(next(r.source for r in reports if not r.error))
        self.review_page.load(session, self.dictionary, readable, first.parent / "Anonymisé")
        self.stack.setCurrentWidget(self.review_page)

    def write(self) -> None:
        out_dir = self.review_page.out_dir
        self.progress_page.begin("Anonymisation en cours…")
        self.stack.setCurrentWidget(self.progress_page)
        worker = WriteWorker(self.session, self.reports, out_dir)
        worker.progress.connect(self.progress_page.update_progress)
        worker.finished.connect(lambda reports: self._written(reports, out_dir))
        worker.failed.connect(self._failed)
        self._thread = start(worker, self)

    def _written(self, reports, out_dir: Path) -> None:
        keep = self.review_page.keep_table.isChecked()
        self.prefs["garder_table"] = keep
        settings.save_prefs(self.prefs)
        saved = False
        sources = [r.source for r in reports if not r.error]
        if keep and sources:
            try:
                self.store.save_session(self.session, sources)
                saved = True
            except Exception as exc:
                QMessageBox.warning(self, "Table non enregistrée",
                                    f"La table de correspondance n'a pas pu être enregistrée :\n{exc}")
        self.result_page.show_reports(reports, out_dir, saved)
        self.stack.setCurrentWidget(self.result_page)

    def _failed(self, message: str) -> None:
        QMessageBox.critical(self, "Erreur", f"Une erreur est survenue :\n{message}")
        self.stack.setCurrentWidget(self.files_page)

    def restart(self) -> None:
        self.session, self.reports = None, None
        self.files_page.clear()
        self.stack.setCurrentWidget(self.files_page)


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("NobodyDoc")
    style.apply(app)
    app.setWindowIcon(QIcon(str(RESOURCES / "icone.png")))
    window = MainWindow()
    window.show()
    # Fichiers passés en argument (glisser sur l'icône de l'exécutable).
    args = [Path(a) for a in app.arguments()[1:] if Path(a).exists()]
    if args:
        window.files_page.add_paths(args)
    return app.exec()
