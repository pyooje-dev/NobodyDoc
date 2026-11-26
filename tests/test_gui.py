"""Parcours complet de l'interface, sans affichage (QT_QPA_PLATFORM=offscreen)."""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from conftest import make_docx, make_xlsx  # noqa: E402


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    box = QtWidgets.QMessageBox
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(box, name, staticmethod(lambda *a, **k: box.Ok))
    monkeypatch.setattr(box, "question", staticmethod(lambda *a, **k: box.Yes))
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def run_analysis(window, app):
    from nobodydoc.gui.workers import AnalyzeWorker

    worker = AnalyzeWorker(list(window.files_page.files), window.dictionary, False)
    worker.finished.connect(window._analyzed)
    worker.run()
    app.processEvents()


def test_full_flow(app, tmp_path):
    from nobodydoc import settings
    from nobodydoc.gui.app import MainWindow
    from nobodydoc.gui.workers import WriteWorker

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "cr.docx").write_bytes(make_docx())
    (docs / "clients.xlsx").write_bytes(make_xlsx())
    (docs / "photo.jpg").write_bytes(b"x")

    window = MainWindow()
    window.files_page.add_paths([docs])  # un dossier entier : le .jpg est ignoré
    assert [p.name for p in window.files_page.files] == ["clients.xlsx", "cr.docx"]

    run_analysis(window, app)
    review = window.review_page
    assert window.stack.currentWidget() is review
    assert review.table.rowCount() > 3

    # Ajout manuel mémorisé dans le dictionnaire
    review.new_term.setText("Facturation")
    review.new_category.setCurrentText("Rubrique")
    review._add_term()
    assert "[RUBRIQUE_1]" in window.session.entities
    assert "Facturation" in settings.dictionary_path().read_text(encoding="utf-8-sig")

    # Décocher le téléphone : il doit rester en clair
    from nobodydoc.gui.app import COL_CHECK
    from PySide6.QtCore import Qt

    for row in range(review.table.rowCount()):
        if review.table.item(row, COL_CHECK).data(Qt.UserRole) == "[TELEPHONE_1]":
            review.table.item(row, COL_CHECK).setCheckState(Qt.Unchecked)
    assert not window.session.entities["[TELEPHONE_1]"].enabled

    out_dir = tmp_path / "sortie"
    review.set_out_dir(out_dir)
    worker = WriteWorker(window.session, window.reports, out_dir)
    worker.finished.connect(lambda reports: window._written(reports, out_dir))
    worker.run()
    app.processEvents()
    assert window.stack.currentWidget() is window.result_page

    import docx

    text = "\n".join(p.text for p in docx.Document(out_dir / "cr_anonymise.docx").paragraphs)
    assert "06 12 34 56 78" in text  # décoché
    assert "[RUBRIQUE_1]" in text and "Facturation" not in text


def test_never_mask_adds_exclusion(app, tmp_path):
    from nobodydoc.gui.app import COL_CHECK, MainWindow
    from PySide6.QtCore import Qt

    (tmp_path / "cr.docx").write_bytes(make_docx())
    window = MainWindow()
    window.files_page.add_paths([tmp_path / "cr.docx"])
    run_analysis(window, app)
    review = window.review_page
    row = next(r for r in range(review.table.rowCount())
               if review.table.item(r, COL_CHECK).data(Qt.UserRole).startswith("[IBAN_"))
    review.table.selectRow(row)
    review._never_mask_selected()
    assert window.dictionary.is_excluded("FR76 3000 6000 0112 3456 7890 189")


def test_dictionary_dialog_roundtrip(app):
    from nobodydoc.dictionary import CompanyDictionary, DictionaryTerm
    from nobodydoc.gui.dictionary_dialog import DictionaryDialog

    d = CompanyDictionary([DictionaryTerm("Acme", "CLIENT", ["ACME Corp"])], ["Microsoft"])
    dialog = DictionaryDialog(d)
    dialog._add_row("Zèbre", "projet", "")
    result = dialog.result_dictionary()
    assert [(t.term, t.category, t.variants) for t in result.terms] == [
        ("Acme", "CLIENT", ["ACME Corp"]), ("Zèbre", "PROJET", [])]
    assert result.exclusion_list == ["Microsoft"]


def test_restore_tab(app, tmp_path):
    from nobodydoc.gui.app import MainWindow
    from nobodydoc.gui.workers import WriteWorker

    (tmp_path / "cr.docx").write_bytes(make_docx())
    window = MainWindow()
    window.files_page.add_paths([tmp_path / "cr.docx"])
    run_analysis(window, app)
    out_dir = tmp_path / "sortie"
    worker = WriteWorker(window.session, window.reports, out_dir)
    worker.finished.connect(lambda reports: window._written(reports, out_dir))
    worker.run()
    app.processEvents()

    page = window.restore_page
    window.tabs.setCurrentWidget(page)
    assert len(page.tables) == 1
    page.input.setPlainText("Merci de rappeler [TELEPHONE_1] ou écrire à [EMAIL_1]. [PERSONNE_99] ?")
    page.restore_text()
    assert page.output.toPlainText().startswith("Merci de rappeler 06 12 34 56 78 ou écrire à claire.martin@")
    assert "[PERSONNE_99]" in page.text_status.text()

    QtWidgets.QMessageBox.exec = lambda self: 0  # fenêtre de compte rendu
    [report] = page.restore_paths([out_dir / "cr_anonymise.docx"])
    assert not report.error and (out_dir / "cr_restaure.docx").exists()
