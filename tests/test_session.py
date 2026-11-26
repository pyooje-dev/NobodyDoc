import pytest

from nobodydoc.session import AnonymizationSession, SessionConfig


def make(dictionary, ner=None, use_ner=False):
    return AnonymizationSession(SessionConfig(use_ner=use_ner), dictionary, ner=ner)


def test_dictionary_terms_and_variants_share_a_token(dictionary):
    s = make(dictionary)
    text = "Acme, ACME Corp et Acme Industries travaillent avec la DSI. La dsi en minuscules reste."
    s.collect([text])
    out = s.anonymize_text(text)
    assert out == "[CLIENT_1], [CLIENT_1] et [CLIENT_1] travaillent avec la [DEPARTEMENT_1]. La dsi en minuscules reste."


def test_same_value_same_token_across_texts(dictionary):
    s = make(dictionary)
    a, b = "Appelez le 06 12 34 56 78.", "Ou le 06.12.34.56.78 / +33 6 12 34 56 78"
    s.collect([a, b])
    assert s.anonymize_text(a) == "Appelez le [TELEPHONE_1]."
    assert s.anonymize_text(b) == "Ou le [TELEPHONE_1] / [TELEPHONE_1]"


def test_exclusions_are_never_masked(dictionary):
    s = make(dictionary)
    s.add_manual("Microsoft", "ORGANISATION")
    assert s.anonymize_text("Microsoft Teams") == "Microsoft Teams"


def test_disabled_entity_is_kept(dictionary):
    s = make(dictionary)
    s.collect(["Projet Phoenix"])
    s.set_enabled("[PRODUIT_1]", False)
    assert s.anonymize_text("Projet Phoenix") == "Projet Phoenix"


def test_manual_term_masked_everywhere(dictionary):
    s = make(dictionary)
    s.add_manual("Opération Zèbre", "PROJET")
    assert s.anonymize_text("L'opération zèbre démarre.") == "L'[PROJET_1] démarre."


def test_existing_placeholders_untouched(dictionary):
    s = make(dictionary)
    assert s.anonymize_text("[PERSONNE_1] et [CLIENT_1]") == "[PERSONNE_1] et [CLIENT_1]"


def test_ner_name_found_once_is_masked_everywhere(dictionary, ner):
    if ner is None:
        pytest.skip("modèle spaCy absent")
    s = make(dictionary, ner=ner, use_ner=True)
    s.collect(["Le contrat a été signé par Jean Dupont hier à Paris."])
    # Texte isolé (cellule Excel) que le modèle seul ne reconnaîtrait pas forcément.
    assert s.anonymize_text("DUPONT") == "[PERSONNE_1]"
    assert s.anonymize_text("Mme Dupont") == "Mme [PERSONNE_1]"
    assert s.anonymize_text("Jean Dupont") == "[PERSONNE_1]"


def test_dictionary_csv_roundtrip(tmp_path, dictionary):
    from nobodydoc.dictionary import CompanyDictionary

    dictionary.add_term("Opération Zèbre", "projet", ["Zèbre"])
    path = tmp_path / "dico.csv"
    dictionary.save(path)
    loaded = CompanyDictionary.load(path)
    assert [t.term for t in loaded.terms] == ["Acme", "DSI", "Phoenix", "Opération Zèbre"]
    assert loaded.terms[-1].category == "PROJET" and loaded.terms[-1].variants == ["Zèbre"]
    assert loaded.is_excluded("microsoft")
