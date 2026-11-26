"""Éditeur du dictionnaire de l'entreprise."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..dictionary import CompanyDictionary, DictionaryTerm
from ..entities import normalize_category

FILE_FILTER = "Dictionnaire (*.csv *.json)"


class DictionaryDialog(QDialog):
    def __init__(self, dictionary: CompanyDictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle("Dictionnaire de l'entreprise")
        self.resize(760, 540)

        intro = QLabel(
            "Les <b>termes à masquer</b> sont toujours remplacés, même si l'outil ne les "
            "reconnaît pas seul : clients, produits, projets, acronymes, départements… "
            "La catégorie donne le nom du jeton (CLIENT → [CLIENT_1]). Les variantes "
            "(séparées par | ) reçoivent le même jeton. Un terme écrit en MAJUSCULES n'est "
            "cherché qu'en majuscules."
        )
        intro.setWordWrap(True)
        intro.setObjectName("subtitle")

        # Onglet 1 : termes
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Terme", "Catégorie", "Variantes (séparées par | )"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        for term in dictionary.terms:
            self._add_row(term.term, term.category, " | ".join(term.variants))

        add_term = QPushButton("+ Ajouter un terme")
        add_term.clicked.connect(self._new_term)
        del_term = QPushButton("Supprimer la sélection")
        del_term.clicked.connect(lambda: self._remove_selected_rows(self.table))
        terms_tab = QWidget()
        lay = QVBoxLayout(terms_tab)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(add_term)
        row.addWidget(del_term)
        row.addStretch()
        lay.addLayout(row)

        # Onglet 2 : exclusions
        self.exclusions = QListWidget()
        for value in dictionary.exclusion_list:
            self._add_exclusion_item(value)
        add_excl = QPushButton("+ Ajouter un mot")
        add_excl.clicked.connect(self._new_exclusion)
        del_excl = QPushButton("Supprimer la sélection")
        del_excl.clicked.connect(
            lambda: [self.exclusions.takeItem(self.exclusions.row(i)) for i in self.exclusions.selectedItems()]
        )
        excl_tab = QWidget()
        lay2 = QVBoxLayout(excl_tab)
        hint = QLabel("Ces mots ne sont jamais masqués (noms de logiciels, de villes, termes génériques…).")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        lay2.addWidget(hint)
        lay2.addWidget(self.exclusions)
        row2 = QHBoxLayout()
        row2.addWidget(add_excl)
        row2.addWidget(del_excl)
        row2.addStretch()
        lay2.addLayout(row2)

        tabs = QTabWidget()
        tabs.addTab(terms_tab, "Termes à masquer")
        tabs.addTab(excl_tab, "Ne jamais masquer")

        import_btn = QPushButton("Importer…")
        import_btn.setToolTip("Ajoute les termes d'un fichier CSV ou JSON")
        import_btn.clicked.connect(self._import)
        export_btn = QPushButton("Exporter…")
        export_btn.setToolTip("Enregistre une copie à partager avec des collègues")
        export_btn.clicked.connect(self._export)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addWidget(import_btn)
        bottom.addWidget(export_btn)
        bottom.addStretch()
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------ lignes

    def _add_row(self, term: str, category: str, variants: str) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((term, category, variants)):
            self.table.setItem(row, col, QTableWidgetItem(value))
        return row

    def _new_term(self) -> None:
        row = self._add_row("", "CLIENT", "")
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def _add_exclusion_item(self, value: str) -> QListWidgetItem:
        item = QListWidgetItem(value)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.exclusions.addItem(item)
        return item

    def _new_exclusion(self) -> None:
        item = self._add_exclusion_item("")
        self.exclusions.setCurrentItem(item)
        self.exclusions.editItem(item)

    @staticmethod
    def _remove_selected_rows(table: QTableWidget) -> None:
        for row in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(row)

    # ------------------------------------------------------------------ données

    def _collect(self) -> tuple[list[DictionaryTerm], list[str]]:
        terms = []
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, c).text().strip() if self.table.item(row, c) else "" for c in range(3)]
            if not cells[0]:
                continue
            variants = [v.strip() for v in cells[2].split("|") if v.strip()]
            terms.append(DictionaryTerm(cells[0], normalize_category(cells[1] or "DIVERS"), variants))
        exclusions = [self.exclusions.item(i).text().strip() for i in range(self.exclusions.count())]
        return terms, [e for e in exclusions if e]

    def result_dictionary(self) -> CompanyDictionary:
        terms, exclusions = self._collect()
        return CompanyDictionary(terms, exclusions)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un dictionnaire", "", FILE_FILTER)
        if not path:
            return
        try:
            other = CompanyDictionary.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import impossible", f"Le fichier n'a pas pu être lu :\n{exc}")
            return
        existing = {self.table.item(r, 0).text().casefold() for r in range(self.table.rowCount()) if self.table.item(r, 0)}
        added = 0
        for term in other.terms:
            if term.term.casefold() not in existing:
                self._add_row(term.term, term.category, " | ".join(term.variants))
                added += 1
        current = {self.exclusions.item(i).text().casefold() for i in range(self.exclusions.count())}
        for value in other.exclusion_list:
            if value.casefold() not in current:
                self._add_exclusion_item(value)
        QMessageBox.information(self, "Import terminé", f"{added} terme(s) ajouté(s).")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le dictionnaire", "dictionnaire.csv", FILE_FILTER)
        if path:
            self.result_dictionary().save(Path(path))
