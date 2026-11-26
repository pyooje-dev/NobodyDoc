import email
import io
import zipfile

import pytest

from nobodydoc.pipeline import anonymize_files
from nobodydoc.session import AnonymizationSession, SessionConfig
from nobodydoc.formats.ooxml import redistribute
from conftest import SECRETS, make_docx, make_eml, make_pptx, make_xlsx

NAME_SECRETS = {"Jean Dupont", "Dupont", "Claire Martin", "Sophie Bernard"}


def all_text_of_zip(data: bytes) -> str:
    chunks = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            content = zf.read(name)
            if name.endswith((".docx", ".xlsx", ".pptx")):
                chunks.append(all_text_of_zip(content))
            elif name.endswith((".xml", ".rels")):
                chunks.append(content.decode("utf-8", "replace"))
    return "\n".join(chunks)


def all_text_of_eml(data: bytes) -> str:
    msg = email.message_from_bytes(data)
    chunks = [str(email.header.make_header(email.header.decode_header(str(v)))) for _, v in msg.items()]
    for part in msg.walk():
        chunks += [str(v) for _, v in part.items()]
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() and payload[:2] == b"PK":
            chunks.append(all_text_of_zip(payload))
        else:
            chunks.append(payload.decode("utf-8", "replace"))
    return "\n".join(chunks)


def assert_no_leak(text: str, ner_on: bool):
    for secret in SECRETS:
        if secret in NAME_SECRETS and not ner_on:
            continue
        assert secret not in text, f"fuite : {secret!r}"
    assert "ACME" not in text


@pytest.fixture
def run(tmp_path, dictionary, ner):
    def _run(name: str, data: bytes):
        src = tmp_path / name
        src.write_bytes(data)
        session = AnonymizationSession(SessionConfig(use_ner=ner is not None), dictionary, ner=ner)
        [report] = anonymize_files([src], session, tmp_path / "out")
        assert not report.error, report.error
        from pathlib import Path
        return Path(report.output).read_bytes(), report, session

    return _run


def test_redistribute_keeps_runs():
    segs = ["Présents : Jean ", "Du", "pont et Claire."]
    full = "".join(segs)
    start = full.index("Jean Dupont")
    out = redistribute(segs, [(start, start + len("Jean Dupont"), "[PERSONNE_1]")])
    assert out == ["Présents : [PERSONNE_1]", "", " et Claire."]


def test_docx(run, ner):
    out, report, _ = run("cr.docx", make_docx())
    assert_no_leak(all_text_of_zip(out), ner is not None)
    import docx

    doc = docx.Document(io.BytesIO(out))  # le fichier s'ouvre toujours
    assert doc.core_properties.author == ""
    assert any(r.bold for p in doc.paragraphs for r in p.runs)  # mise en forme conservée
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "[TELEPHONE_1]" in text and "[CLIENT_1]" in text and "Microsoft Teams" in text
    assert report.total > 0


def test_xlsx(run, ner):
    out, report, _ = run("clients.xlsx", make_xlsx())
    assert_no_leak(all_text_of_zip(out), ner is not None)
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(out))
    ws = wb["Clients"]
    assert ws["B2"].value == "[CLIENT_1]" and ws["B3"].value == "[CLIENT_1]"
    assert ws["E2"].value == 1250 and ws["F1"].value == "=SUM(E2:E3)"
    if ner is not None:
        assert ws["A2"].value.startswith("[PERSONNE_")


def test_pptx(run, ner):
    out, _, _ = run("deck.pptx", make_pptx())
    assert_no_leak(all_text_of_zip(out), ner is not None)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(out))
    assert prs.slides[0].shapes.title.text == "Projet [PRODUIT_1] pour [CLIENT_1]"


def test_eml_with_attachments(run, ner):
    out, report, _ = run("mail.eml", make_eml(make_docx()))
    text = all_text_of_eml(out)
    assert_no_leak(text, ner is not None)
    assert "10.0.0.12" not in text and "acme-industries" not in text
    msg = email.message_from_bytes(out)
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert names == ["Compte rendu [CLIENT_1].docx"]  # le PDF a été retiré
    assert any("contrat.pdf" in w for w in report.warnings)


def test_consistent_tokens_across_files(tmp_path, dictionary, ner):
    files = {"a.docx": make_docx(), "b.xlsx": make_xlsx(), "c.pptx": make_pptx()}
    paths = []
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        paths.append(tmp_path / name)
    session = AnonymizationSession(SessionConfig(use_ner=ner is not None), dictionary, ner=ner)
    reports = anonymize_files(paths, session, tmp_path / "out")
    assert all(not r.error for r in reports)
    phone_tokens = {p for p, e in session.entities.items() if e.category == "TELEPHONE"}
    assert phone_tokens == {"[TELEPHONE_1]"}
