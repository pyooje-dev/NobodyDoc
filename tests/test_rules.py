from nobodydoc.detectors.rules import find_rule_spans


def found(text, category):
    return [s.text for s in find_rule_spans(text) if s.category == category]


def test_emails():
    assert found("Écrire à jean-luc.o'neil+rh@sous.domaine.fr.", "EMAIL") == ["jean-luc.o'neil+rh@sous.domaine.fr"]


def test_french_phones():
    text = "Tél 06 12 34 56 78, 01.23.45.67.89, +33 6 12 34 56 78, +33 (0)1 23 45 67 89, 0033612345678"
    assert len(found(text, "TELEPHONE")) == 5


def test_international_phone():
    assert found("Londres : +44 20 7946 0958", "TELEPHONE") == ["+44 20 7946 0958"]


def test_phone_does_not_match_amounts_or_dates():
    assert found("Montant 1 250 000 euros le 12/03/2024, réf 2024-0012", "TELEPHONE") == []


def test_iban_checksum_and_trailing_word():
    text = "IBAN FR76 3000 6000 0112 3456 7890 189 BIC AGRIFRPP"
    assert found(text, "IBAN") == ["FR76 3000 6000 0112 3456 7890 189"]
    assert found("FR76 3000 6000 0112 3456 7890 188", "IBAN") == []  # clé fausse


def test_card_luhn():
    assert found("Carte 4970 1012 3456 7899", "CARTE_BANCAIRE") == []
    assert found("Carte 4111 1111 1111 1111", "CARTE_BANCAIRE") == ["4111 1111 1111 1111"]


def test_nir_with_key():
    assert found("NIR 1 85 05 78 006 084 91", "NIR") == ["1 85 05 78 006 084 91"]
    assert found("NIR 1 85 05 78 006 084 36", "NIR") == []


def test_siret_and_vat():
    assert found("SIRET : 732 829 320 00074", "ID_ENTREPRISE") == ["732 829 320 00074"]
    assert found("TVA FR40303265045", "ID_ENTREPRISE") == ["FR40303265045"]


def test_address_merged_with_postcode():
    text = "Siège : 12 bis rue des Lilas, 69003 Lyon CEDEX 03. Merci."
    assert found(text, "ADRESSE") == ["12 bis rue des Lilas, 69003 Lyon CEDEX 03"]


def test_postcode_city_compound():
    assert found("Livraison à 93200 Saint-Denis demain", "ADRESSE") == ["93200 Saint-Denis"]
    assert found("Bureau : 72000 Le Mans", "ADRESSE") == ["72000 Le Mans"]


def test_ip_and_url():
    text = "Serveur 192.168.1.10. Voir https://intranet.acme.fr/rh?id=3, version 1.2.3."
    assert found(text, "IP") == ["192.168.1.10"]
    assert found(text, "URL") == ["https://intranet.acme.fr/rh?id=3"]
