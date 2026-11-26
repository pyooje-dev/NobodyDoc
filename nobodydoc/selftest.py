"""Auto-test de l'exécutable : vérifie que le modèle, le chiffrement et l'interface
fonctionnent une fois empaquetés. Utilisé par la fabrication automatique.

    NobodyDoc.exe --auto-test resultat.txt
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

SAMPLE = ("Bonjour, je suis Jean Dupont de la société Acme Industries. Appelez Claire Martin "
          "au 06 12 34 56 78 ou écrivez à claire.martin@acme.fr. IBAN FR76 3000 6000 0112 3456 7890 189.")

MINIMAL_DOCX = {
    "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    "word/document.xml": '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t xml:space="preserve">Contrat signé par Jean </w:t></w:r><w:r><w:t>Dupont, 06 12 34 56 78.</w:t></w:r></w:p></w:body></w:document>',
}


def _checks(log) -> None:
    from .detectors.ner import NerDetector
    from .pipeline import anonymize_files, restore_files
    from .session import AnonymizationSession
    from .vault import TableStore

    ner = NerDetector()
    assert ner.available, "modèle de langue introuvable"
    log(f"modèle : {ner.model_name}")

    session = AnonymizationSession(ner=ner)
    session.collect([SAMPLE])
    out = session.anonymize_text(SAMPLE)
    for secret in ("Jean Dupont", "Claire Martin", "06 12 34 56 78", "claire.martin@acme.fr", "FR76"):
        assert secret not in out, f"non masqué : {secret}"
    log(f"texte : {out}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in MINIMAL_DOCX.items():
                zf.writestr(name, content)
        (tmp / "test.docx").write_bytes(buf.getvalue())
        session = AnonymizationSession(ner=ner)
        [report] = anonymize_files([tmp / "test.docx"], session, tmp / "out")
        assert not report.error, report.error
        anonymized = zipfile.ZipFile(tmp / "out" / "test_anonymise.docx").read("word/document.xml").decode()
        assert "Dupont" not in anonymized and "[PERSONNE_1]" in anonymized, anonymized
        store = TableStore(tmp / "profil")
        store.save_session(session, [str(tmp / "test.docx")])
        [table] = store.list()
        [restored] = restore_files([tmp / "out" / "test_anonymise.docx"], table)
        back = zipfile.ZipFile(restored.output).read("word/document.xml").decode()
        assert "Jean Dupont" in back, back
        log("docx + table chiffrée + restauration : ok")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .gui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    window.close()
    log("interface : ok")


def main(argv: list[str]) -> int:
    target = Path(argv[argv.index("--auto-test") + 1]) if len(argv) > argv.index("--auto-test") + 1 else None
    lines: list[str] = []
    code = 0
    try:
        _checks(lines.append)
        lines.append("AUTO-TEST OK")
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("AUTO-TEST ÉCHEC")
        code = 1
    text = "\n".join(lines)
    if target:
        target.write_text(text, encoding="utf-8")
    if sys.stdout:
        try:
            print(text)
        except Exception:
            pass
    return code
