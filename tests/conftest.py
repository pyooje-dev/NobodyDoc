"""Documents d'exemple générés à la volée (aucune vraie donnée)."""

from __future__ import annotations

import io
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from nobodydoc.detectors.ner import NerDetector
from nobodydoc.dictionary import CompanyDictionary, DictionaryTerm

# Valeurs qui ne doivent apparaître nulle part dans les fichiers produits.
SECRETS = [
    "Jean Dupont", "Dupont", "Claire Martin", "claire.martin@acme-industries.fr",
    "06 12 34 56 78", "FR76 3000 6000 0112 3456 7890 189", "12 bis rue des Lilas",
    "Acme", "DSI", "Phoenix", "Sophie Bernard",
]


@pytest.fixture(scope="session")
def ner():
    detector = NerDetector()
    return detector if detector.available else None


@pytest.fixture
def dictionary():
    return CompanyDictionary(
        [
            DictionaryTerm("Acme", "CLIENT", ["Acme Industries", "ACME Corp"]),
            DictionaryTerm("DSI", "DEPARTEMENT"),
            DictionaryTerm("Phoenix", "PRODUIT"),
        ],
        exclusions=["Microsoft"],
    )


PARAGRAPH = (
    "Bonjour, je suis Jean Dupont, responsable chez Acme Industries. "
    "Merci de contacter Claire Martin (DSI) au 06 12 34 56 78 ou par mail : "
    "claire.martin@acme-industries.fr. Facturation : 12 bis rue des Lilas, 69003 Lyon. "
    "IBAN FR76 3000 6000 0112 3456 7890 189. Le projet Phoenix tourne sous Microsoft Teams."
)


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.core_properties.author = "Sophie Bernard"
    d.core_properties.last_modified_by = "Sophie Bernard"
    d.core_properties.title = "Compte rendu Acme"
    d.sections[0].header.paragraphs[0].text = "Confidentiel - Acme - DSI"
    d.sections[0].footer.paragraphs[0].text = "Rédigé par Jean Dupont"
    d.add_heading("Réunion Phoenix", 1)
    p = d.add_paragraph()
    # Nom découpé en plusieurs runs avec des mises en forme différentes.
    p.add_run("Présents : Jean ")
    bold = p.add_run("Du")
    bold.bold = True
    p.add_run("pont et Claire Martin.")
    para = d.add_paragraph(PARAGRAPH)
    d.add_comment(para.runs, text="À valider par M. Dupont", author="Sophie Bernard", initials="SB")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Contact"
    table.cell(0, 1).text = "claire.martin@acme-industries.fr"
    table.cell(1, 0).text = "Téléphone"
    table.cell(1, 1).text = "06 12 34 56 78"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_xlsx() -> bytes:
    import openpyxl
    from openpyxl.comments import Comment

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Clients"
    ws.append(["Nom", "Société", "Email", "Téléphone", "Montant"])
    ws.append(["Jean Dupont", "Acme", "claire.martin@acme-industries.fr", "06 12 34 56 78", 1250])
    ws.append(["Claire Martin", "ACME Corp", "", "", 300])
    ws["A5"] = PARAGRAPH
    ws["B2"].comment = Comment("Vérifier avec la DSI", "Sophie Bernard")
    ws["F1"] = "=SUM(E2:E3)"
    wb.properties.creator = "Sophie Bernard"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pptx() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Projet Phoenix pour Acme"
    body = slide.placeholders[1].text_frame
    body.text = "Chef de projet : Jean Dupont"
    para = body.add_paragraph()
    run1 = para.add_run()
    run1.text = "Contact : Claire "
    run2 = para.add_run()
    run2.text = "Martin, 06 12 34 56 78"
    run2.font.bold = True
    slide.notes_slide.notes_text_frame.text = PARAGRAPH
    prs.core_properties.author = "Sophie Bernard"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_eml(attachment: bytes) -> bytes:
    msg = MIMEMultipart("mixed")
    msg["From"] = '"Jean Dupont" <jean.dupont@acme-industries.fr>'
    msg["To"] = '"Claire Martin" <claire.martin@acme-industries.fr>'
    msg["Subject"] = "Projet Phoenix - point avec la DSI"
    msg["Received"] = "from mail.acme-industries.fr (10.0.0.12) by mx.example.com"
    msg["Message-ID"] = "<abc123@acme-industries.fr>"
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(PARAGRAPH + "\n\nCordialement,\nJean Dupont", "plain", "utf-8"))
    alt.attach(MIMEText(f"<html><body><p>{PARAGRAPH}</p><p><a href='mailto:claire.martin@acme-industries.fr'>Claire Martin</a></p></body></html>", "html", "utf-8"))
    msg.attach(alt)
    part = MIMEApplication(attachment, Name="Compte rendu Acme.docx")
    part.add_header("Content-Disposition", "attachment", filename="Compte rendu Acme.docx")
    msg.attach(part)
    pdf = MIMEApplication(b"%PDF-1.4 Jean Dupont", Name="contrat.pdf")
    pdf.add_header("Content-Disposition", "attachment", filename="contrat.pdf")
    msg.attach(pdf)
    return msg.as_bytes()
