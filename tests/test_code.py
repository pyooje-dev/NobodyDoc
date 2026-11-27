"""Requêtes SQL, code source et fichiers de configuration."""

import re

from nobodydoc.detectors.rules import find_rule_spans
from nobodydoc.formats import SUPPORTED_EXTENSIONS, handler_for
from nobodydoc.formats.code import prose_fragments
from nobodydoc.pipeline import anonymize_files, restore_files
from nobodydoc.session import AnonymizationSession, SessionConfig
from nobodydoc.vault import MappingTable


def found(text, category=None):
    return [(s.category, s.text) if category is None else s.text
            for s in find_rule_spans(text) if category in (None, s.category)]


SQL = """-- Extraction pour Jean Dupont
SELECT nom, email FROM crm.clients WHERE email = 'jean.dupont@acme.fr' AND ville = 'Lyon';
INSERT INTO logs VALUES ('10.12.0.5', 'https://intranet.acme.local/api?token=abc123');
CREATE USER paie WITH PASSWORD 'Ete2024!';
-- jdbc:postgresql://db-prod.acme.internal:5432/crm?user=admin&password=S3cret!
"""

PYTHON = '''DB_URL = "postgresql://admin:S3cret!@db-prod.acme.internal:5432/crm"
HOST = "srv-paie01.acme.local"
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"
headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc"}
password = get_password()
send_mail("marie.martin@acme.fr")
'''

CODE_SECRETS = [
    "jean.dupont@acme.fr", "10.12.0.5", "intranet.acme.local", "Ete2024!", "db-prod.acme.internal",
    "S3cret!", "srv-paie01", "AKIAIOSFODNN7EXAMPLE", "ghp_1234", "eyJhbGci", "marie.martin",
]


def test_code_extensions_are_supported():
    for ext in (".sql", ".py", ".js", ".ts", ".java", ".cs", ".php", ".sh", ".ps1",
                ".yaml", ".ini", ".env", ".properties", ".xml", ".config"):
        assert ext in SUPPORTED_EXTENSIONS
        assert handler_for(ext) is not None


def test_email_keeps_its_quotes():
    assert found("WHERE email = 'jean.dupont@acme.fr'", "EMAIL") == ["jean.dupont@acme.fr"]
    assert found("o'neil@acme.fr", "EMAIL") == ["o'neil@acme.fr"]


def test_connection_uri_masks_only_its_sensitive_parts():
    spans = found("mongodb+srv://svc_app:Pa55w0rd@cluster0.acme.fr/ventes")
    assert spans == [("SECRET", "Pa55w0rd"), ("IDENTIFIANT", "svc_app"), ("HOTE", "cluster0.acme.fr")]


def test_connection_string_keys():
    text = "Server=SRV-SQL01;Database=Paie;User Id=svc_paie;Password=P@ss2024;"
    assert set(found(text)) == {("HOTE", "SRV-SQL01"), ("IDENTIFIANT", "svc_paie"), ("SECRET", "P@ss2024")}


def test_secrets_after_a_telling_name():
    assert found('DB_PASSWORD=hunter2\napi_key: "k-123456"\n"client_secret": "zZ9"', "SECRET") == [
        "hunter2", "k-123456", "zZ9"]
    assert found("Mot de passe : Azerty123", "SECRET") == ["Azerty123"]


def test_no_secret_in_ordinary_code_or_prose():
    text = (
        "password = get_password()\npassword = os.environ['PWD']\ntoken: string;\n"
        "login(user=user, password=password)\ncompass = 'north'\npassword = None\n"
        "WHERE password = ? AND token = :token\nMot de passe : voir avec la DSI\n"
        'label = {"password": "Mot de passe"}\nhost = "localhost"\n'
    )
    assert found(text, "SECRET") + found(text, "IDENTIFIANT") + found(text, "HOTE") == []


def test_known_key_formats():
    keys = [
        "AKIAIOSFODNN7EXAMPLE", "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB",
        "xoxb-123456789012-abcdefghij", "sk_live_abcdefghijklmnop1234",
        "AIzaSyA1234567890abcdefghijklmnopqrstuv",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl",
    ]
    for key in keys:
        assert found(f"x {key} y", "SECRET") == [key]
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAKC\n-----END RSA PRIVATE KEY-----"
    assert found(pem, "SECRET") == [pem]


def test_internal_hosts():
    assert found("ping srv-paie01.acme.local puis db.prod.internal", "HOTE") == [
        "srv-paie01.acme.local", "db.prod.internal"]
    assert found("import settings.local.py ; package com.acme.internal;", "HOTE") == []


def test_ipv6():
    assert found("serveur 2001:db8:85a3::8a2e:370:7334 à 12:30:45", "IP") == ["2001:db8:85a3::8a2e:370:7334"]


def test_language_model_reads_only_comments_and_strings():
    frags = prose_fragments(SQL, "sql")
    assert "Extraction pour Jean Dupont" in frags
    assert not any("SELECT" in f for f in frags)
    assert prose_fragments("# Auteur : Claire Martin\nDB_HOST=srv01\n", "kv") == ["Auteur : Claire Martin"]
    assert prose_fragments('// note de Paul Durand\nconst x = "Server=a;User=b";', "c") == ["note de Paul Durand"]


def test_code_files_stay_valid_and_restore(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "extraction.sql").write_bytes(SQL.replace("\n", "\r\n").encode("cp1252"))
    (src / "config.py").write_text(PYTHON, encoding="utf-8")
    session = AnonymizationSession(SessionConfig(use_ner=False))
    reports = anonymize_files(sorted(src.iterdir()), session, tmp_path / "out")
    assert all(not r.error for r in reports)

    sql = (tmp_path / "out" / "extraction_anonymise.sql").read_bytes()
    py = (tmp_path / "out" / "config_anonymise.py").read_bytes()
    assert not py.startswith(b"\xef\xbb\xbf")  # pas de BOM ajouté
    assert b"\r\n" in sql and b"\n" not in sql.replace(b"\r\n", b"")  # fins de ligne conservées
    for secret in CODE_SECRETS:
        assert secret.encode() not in sql + py, secret
    assert re.search(rb"WHERE email = '\[EMAIL_\d+\]' AND", sql)
    assert b"postgresql://[IDENTIFIANT_1]:[SECRET_1]@[HOTE_1]:5432/crm" in py
    assert b"password = get_password()" in py
    compile(py.decode(), "config_anonymise.py", "exec")  # toujours du Python valide

    table = MappingTable.from_session(session, [])
    restored = restore_files([tmp_path / "out" / "config_anonymise.py",
                              tmp_path / "out" / "extraction_anonymise.sql"], table, tmp_path / "back")
    assert all(not r.error for r in restored)
    assert (tmp_path / "back" / "config_restaure.py").read_text(encoding="utf-8") == PYTHON
    assert (tmp_path / "back" / "extraction_restaure.sql").read_bytes() == SQL.replace("\n", "\r\n").encode("cp1252")


def test_secrets_are_case_sensitive():
    session = AnonymizationSession(SessionConfig(use_ner=False))
    text = "password=Abc123\nDB_PASSWORD=aBC123\n"
    session.collect([text])
    out = session.anonymize_text(text)
    assert out == "password=[SECRET_1]\nDB_PASSWORD=[SECRET_2]\n"


def test_bom_is_kept_only_when_present(tmp_path):
    for name, data in (("avec.txt", "﻿jean@acme.fr".encode("utf-8")), ("sans.txt", b"jean@acme.fr")):
        (tmp_path / name).write_bytes(data)
    session = AnonymizationSession(SessionConfig(use_ner=False))
    anonymize_files([tmp_path / "avec.txt", tmp_path / "sans.txt"], session, tmp_path / "out")
    assert (tmp_path / "out" / "avec_anonymise.txt").read_bytes() == b"\xef\xbb\xbf[EMAIL_1]"
    assert (tmp_path / "out" / "sans_anonymise.txt").read_bytes() == b"[EMAIL_1]"


def test_names_in_comments_are_found_by_the_language_model(ner, tmp_path):
    if ner is None:
        import pytest
        pytest.skip("modèle de langue absent")
    path = tmp_path / "script.sql"
    path.write_text("-- Requête préparée par Jean Dupont pour la paie\nSELECT * FROM salaries;\n", encoding="utf-8")
    session = AnonymizationSession(SessionConfig(), ner=ner)
    anonymize_files([path], session, tmp_path / "out")
    out = (tmp_path / "out" / "script_anonymise.sql").read_text(encoding="utf-8")
    assert "Dupont" not in out and "SELECT * FROM salaries;" in out


def test_same_file_names_do_not_overwrite_each_other(tmp_path):
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "config.py").write_text(f'HOST = "srv-{folder}.acme.local"\n', encoding="utf-8")
    session = AnonymizationSession(SessionConfig(use_ner=False))
    reports = anonymize_files([tmp_path / "a" / "config.py", tmp_path / "b" / "config.py"], session, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["config_anonymise.py", "config_anonymise_2.py"]
    assert len({r.output for r in reports}) == 2


def test_dotenv_files(tmp_path):
    (tmp_path / ".env").write_text("DB_PASSWORD=hunter2\n", encoding="utf-8")
    session = AnonymizationSession(SessionConfig(use_ner=False))
    [report] = anonymize_files([tmp_path / ".env"], session, tmp_path / "out")
    assert not report.error
    assert (tmp_path / "out" / "env_anonymise.env").read_text(encoding="utf-8") == "DB_PASSWORD=[SECRET_1]\n"
