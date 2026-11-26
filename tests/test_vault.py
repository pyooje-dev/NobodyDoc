import io

import pytest

from conftest import make_docx
from nobodydoc.pipeline import anonymize_files, restore_files
from nobodydoc.session import AnonymizationSession, SessionConfig
from nobodydoc.vault import MappingTable, TableStore


@pytest.fixture
def store(tmp_path):
    return TableStore(tmp_path / "profil")


@pytest.fixture
def session(dictionary):
    s = AnonymizationSession(SessionConfig(use_ner=False), dictionary)
    s.add_manual("Jean Dupont", "PERSONNE")
    s.collect(["Jean Dupont (Acme) : 06 12 34 56 78, projet Phoenix."])
    return s


def test_table_is_encrypted_and_roundtrips(store, session):
    path = store.save_session(session, ["C:/docs/Licenciement Dupont.docx"])
    raw = path.read_bytes()
    for secret in (b"Dupont", b"Acme", b"06 12", b"Licenciement"):
        assert secret not in raw  # rien de lisible sur le disque
    [table] = store.list()
    assert table.files == ["C:/docs/Licenciement Dupont.docx"]
    assert table.entries["[PERSONNE_1]"].original == "Jean Dupont"


def test_tampered_or_foreign_table_is_refused(store, session, tmp_path):
    path = store.save_session(session, ["a.docx"])
    other = TableStore(tmp_path / "autre_poste")
    with pytest.raises(ValueError):
        other.load(path)  # autre clé : illisible
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        store.load(path)
    assert store.list() == []


def test_restore_text_tolerates_rewritten_tokens(session):
    table = MappingTable.from_session(session, [])
    text = ("[PERSONNE_1] de [CLIENT_1] rappelle au [TELEPHONE_1]. [Personne 1] confirme ; "
            "PERSONNE_1 aussi. La personne 1 de l'équipe n'est pas un jeton. [PRODUIT_9] inconnu.")
    out = table.apply(text).text
    assert out == ("Jean Dupont de Acme rappelle au 06 12 34 56 78. Jean Dupont confirme ; "
                   "Jean Dupont aussi. La personne 1 de l'équipe n'est pas un jeton. [PRODUIT_9] inconnu.")
    assert table.unknown_tokens(text) == ["[PRODUIT_9]"]


def test_disabled_entities_are_not_in_table(session):
    session.set_enabled("[TELEPHONE_1]", False)
    assert "[TELEPHONE_1]" not in MappingTable.from_session(session, []).entries


def test_purge_old_tables(store, session):
    table = MappingTable.from_session(session, ["a.docx"])
    from datetime import timedelta

    table.created -= timedelta(days=100)
    store.save(table)
    store.save_session(session, ["b.docx"])
    assert store.delete_older_than(90) == 1
    assert [t.files for t in store.list()] == [["b.docx"]]


def test_docx_anonymize_then_restore(tmp_path, dictionary, ner, store):
    src = tmp_path / "cr.docx"
    src.write_bytes(make_docx())
    session = AnonymizationSession(SessionConfig(use_ner=ner is not None), dictionary, ner=ner)
    [report] = anonymize_files([src], session, tmp_path / "out")
    store.save_session(session, [str(src)])
    [table] = store.list()

    [restored] = restore_files([tmp_path / "out" / "cr_anonymise.docx"], table)
    assert not restored.error and restored.output.endswith("cr_restaure.docx")
    import docx

    original = "\n".join(p.text for p in docx.Document(src).paragraphs)
    back = "\n".join(p.text for p in docx.Document(restored.output).paragraphs)
    assert "[" not in back
    assert "06 12 34 56 78" in back and "claire.martin@acme-industries.fr" in back
    assert back.count("Phoenix") == original.count("Phoenix")
