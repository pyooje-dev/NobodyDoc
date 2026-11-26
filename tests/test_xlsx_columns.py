import io

import pytest

from nobodydoc.formats.xlsx_columns import header_category, iter_column_entities
from nobodydoc.pipeline import anonymize_files
from nobodydoc.session import AnonymizationSession, SessionConfig


@pytest.mark.parametrize("header, expected", [
    ("NOM Prénom", "PERSONNE"), ("Nom", "PERSONNE"), ("Prénom", "PERSONNE"), ("Contact client", "PERSONNE"),
    ("Salarié", "PERSONNE"), ("Last name", "PERSONNE"), ("Société", "ORGANISATION"),
    ("Raison sociale", "ORGANISATION"), ("Client", "ORGANISATION"), ("Nom du produit", None),
    ("Nom de fichier", None), ("Email", None), ("Montant", None), ("Téléphone contact", None),
])
def test_header_category(header, expected):
    assert header_category(header) == expected


def make_staff_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Liste du personnel"])
    ws.append([])
    ws.append(["NOM Prénom", "Service", "Société", "Montant"])
    for row in (["DUPONT Jean", "Compta", "Établissements Gérard", 120],
                ["MARTIN-LEROY Anne-Sophie", "RH", "Zorglub SARL", 300],
                ["N'GUESSAN Kouassi", "DSI", "Zorglub SARL", 50],
                ["Lefèvre Paul", "Achats", "", 10]):
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_name_column_values_found():
    found = list(iter_column_entities(make_staff_xlsx()))
    assert ("DUPONT Jean", "PERSONNE") in found
    assert ("MARTIN-LEROY Anne-Sophie", "PERSONNE") in found
    assert ("Zorglub SARL", "ORGANISATION") in found
    assert not any(v in ("Compta", "RH", "120") for v, _ in found)


def test_whole_name_cells_masked(tmp_path, ner):
    import openpyxl

    src = tmp_path / "personnel.xlsx"
    src.write_bytes(make_staff_xlsx())
    session = AnonymizationSession(SessionConfig(use_ner=ner is not None), ner=ner)
    [report] = anonymize_files([src], session, tmp_path / "out")
    assert not report.error
    ws = openpyxl.load_workbook(tmp_path / "out" / "personnel_anonymise.xlsx").active
    names = [ws.cell(row=r, column=1).value for r in range(4, 8)]
    assert all(n.startswith("[PERSONNE_") and n.endswith("]") for n in names), names
    assert ws["A3"].value == "NOM Prénom" and ws["B4"].value == "Compta"
    assert ws["C5"].value.startswith("[ORGANISATION_")
