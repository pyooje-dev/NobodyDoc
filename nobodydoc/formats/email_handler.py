"""Mails : .eml (standard) et .msg (Outlook, converti en .eml en sortie).

Sont anonymisés : expéditeur et destinataires (noms et adresses), objet,
corps texte et HTML, noms des pièces jointes, pièces jointes Office et texte
(traitées comme des fichiers à part entière) et mails transférés.
Les en-têtes techniques qui trahissent l'origine (serveurs, adresses IP,
identifiants de message) sont retirés. Les pièces jointes dans un format non
pris en charge (PDF, images...) sont retirées, avec un avertissement.
"""

from __future__ import annotations

import email
import email.encoders
import io
import re
from email.header import Header, decode_header, make_header
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses
from typing import Callable, Iterator

import lxml.html

from ..session import AnonymizationSession
from .base import FileReport

ADDRESS_HEADERS = ("From", "To", "Cc", "Bcc", "Reply-To", "Sender", "Return-Path",
                   "Delivered-To", "X-Original-To", "Disposition-Notification-To")
TEXT_HEADERS = ("Subject", "Thread-Topic", "Comments", "Keywords")
DROP_HEADERS = re.compile(
    r"^(Received|Received-SPF|X-Originating-IP|X-Sender-IP|DKIM-Signature|ARC-.*|"
    r"Authentication-Results.*|X-MS-.*|X-Microsoft-.*|X-Forefront-.*|Thread-Index|"
    r"Message-ID|In-Reply-To|References|X-Mailer|User-Agent|X-Google-.*|X-Gm-.*|"
    r"X-Received|Return-Receipt-To|List-.*|X-Apple-.*|Organization|X-Originating-.*)$",
    re.I,
)
HTML_SKIP = {"script", "style"}
HTML_ATTRS = ("href", "title", "alt")

# (extension) -> handler : fourni par le registre pour traiter les pièces jointes.
HandlerLookup = Callable[[str], object]


def _header_text(value) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:  # en-tête mal encodé
        return str(value)


def _set_header(msg: Message, name: str, value: str) -> None:
    del msg[name]
    try:
        value.encode("ascii")
        msg[name] = value
    except UnicodeEncodeError:
        msg[name] = Header(value, "utf-8")


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("cp1252", "replace")


def _set_part_text(part: Message, text: str) -> None:
    del part["Content-Transfer-Encoding"]
    part.set_payload(text, "utf-8")


def _split_name(filename: str) -> tuple[str, str]:
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        return stem, "." + ext
    return filename, ""


def _anonymize_filename(filename: str, session) -> str:
    stem, ext = _split_name(filename)
    return session.anonymize_text(stem) + ext


def _html_text(html: str) -> str:
    try:
        return lxml.html.document_fromstring(html).text_content()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


class EmailHandler:
    extensions = (".eml", ".msg")

    def __init__(self, lookup: HandlerLookup):
        self._lookup = lookup

    @staticmethod
    def output_extension(ext: str) -> str:
        return ".eml"

    # -------------------------------------------------------------- lecture

    def _load(self, data: bytes, report: FileReport | None = None) -> Message:
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # conteneur OLE = .msg Outlook
            return self._msg_to_email(data, report)
        return email.message_from_bytes(data)

    def _msg_to_email(self, data: bytes, report: FileReport | None) -> Message:
        import extract_msg

        msg = extract_msg.openMsg(data)
        try:
            root = MIMEMultipart("mixed")
            for name, value in (("From", msg.sender), ("To", msg.to), ("Cc", msg.cc),
                                ("Subject", msg.subject), ("Date", msg.date)):
                if value:
                    _set_header(root, name, str(value))
            body = MIMEMultipart("alternative")
            body.attach(MIMEText(msg.body or "", "plain", "utf-8"))
            html = msg.htmlBody
            if html:
                if isinstance(html, bytes):
                    html = html.decode("utf-8", "replace")
                body.attach(MIMEText(html, "html", "utf-8"))
            root.attach(body)
            for att in msg.attachments:
                filename = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None) or "piece_jointe"
                payload = att.data
                if not isinstance(payload, (bytes, bytearray)):
                    if report is not None:
                        report.warn(f"Mail joint « {filename} » retiré (non pris en charge dans un .msg).")
                    continue
                part = MIMEApplication(bytes(payload), Name=filename)
                part.add_header("Content-Disposition", "attachment", filename=filename)
                root.attach(part)
            return root
        finally:
            msg.close()

    def iter_texts(self, data: bytes) -> Iterator[str]:
        msg = self._load(data)
        for part in msg.walk():
            for name in ADDRESS_HEADERS:
                for display, _addr in getaddresses([_header_text(v) for v in part.get_all(name, [])]):
                    if display:
                        yield display
            for name in TEXT_HEADERS:
                if part.get(name):
                    yield _header_text(part.get(name))
            if part.is_multipart() or part.get_content_maintype() == "message":
                continue
            filename = part.get_filename()
            if filename:
                yield _split_name(_header_text(filename))[0]
                handler = self._attachment_handler(filename)
                if handler is not None:
                    yield from handler.iter_texts(part.get_payload(decode=True) or b"")
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                yield from (b for b in _part_text(part).split("\n\n") if b.strip())
            elif ctype == "text/html":
                yield from (b for b in _html_text(_part_text(part)).split("\n\n") if b.strip())

    # -------------------------------------------------------------- écriture

    def anonymize(self, data: bytes, session: AnonymizationSession, report: FileReport) -> bytes:
        msg = self._load(data, report)
        to_remove: list[tuple[Message, Message]] = []
        parents = {id(sub): part for part in msg.walk() if part.is_multipart()
                   for sub in part.get_payload()}

        for part in msg.walk():
            self._anonymize_headers(part, session, report)
            if part.is_multipart() or part.get_content_maintype() == "message":
                continue
            filename = part.get_filename()
            if filename or part.get_content_disposition() == "attachment":
                self._anonymize_attachment(part, filename or "", session, report, parents, to_remove)
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                result = session.apply(_part_text(part))
                report.count(result.replacements)
                _set_part_text(part, result.text)
            elif ctype == "text/html":
                _set_part_text(part, self._anonymize_html(_part_text(part), session, report))
            elif part.get_content_maintype() in ("image", "application", "audio", "video"):
                # Images intégrées (signatures, logos...) sans nom de fichier.
                parent = parents.get(id(part))
                if parent is not None:
                    to_remove.append((parent, part))
                    report.warn("Image(s) intégrée(s) au mail retirée(s) (signature, logo...).")

        for parent, part in to_remove:
            payload = parent.get_payload()
            if part in payload:
                payload.remove(part)
        return msg.as_bytes()

    def _anonymize_headers(self, part: Message, session, report: FileReport) -> None:
        for name in list(dict.fromkeys(part.keys())):
            if DROP_HEADERS.match(name):
                del part[name]
                report.metadata += 1
        for name in ADDRESS_HEADERS:
            values = part.get_all(name)
            if not values:
                continue
            entries = []
            for display, addr in getaddresses([_header_text(v) for v in values]):
                new_display = ""
                if display:
                    result = session.apply(display)
                    new_display = result.text if result.changed else session.pseudonymize_value(display, "PERSONNE")
                new_addr = ""
                if addr:
                    result = session.apply(addr)
                    new_addr = result.text if result.changed else session.pseudonymize_value(addr, "EMAIL")
                entries.append(f'"{new_display}" <{new_addr}>' if new_display else f"<{new_addr}>")
                report.metadata += 1
            _set_header(part, name, ", ".join(entries))
        for name in TEXT_HEADERS:
            if part.get(name):
                result = session.apply(_header_text(part.get(name)))
                if result.changed:
                    report.count(result.replacements)
                    _set_header(part, name, result.text)

    def _anonymize_attachment(self, part, filename, session, report, parents, to_remove) -> None:
        name = _header_text(filename)
        handler = self._attachment_handler(name)
        if handler is None:
            parent = parents.get(id(part))
            if parent is not None:
                to_remove.append((parent, part))
            report.warn(f"Pièce jointe retirée (format non pris en charge) : {_anonymize_filename(name, session)}")
            return
        content = handler.anonymize(part.get_payload(decode=True) or b"", session, report)
        new_name = _anonymize_filename(name, session)
        del part["Content-Transfer-Encoding"]
        part.set_payload(content)
        email.encoders.encode_base64(part)
        if part.get_param("name") is not None:
            part.set_param("name", new_name)
        if part.get("Content-Disposition"):
            part.set_param("filename", new_name, header="Content-Disposition")

    def _attachment_handler(self, filename: str):
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        handler = self._lookup(ext)
        if handler is self:
            return None if ext == ".msg" else handler  # .eml joint : traité, .msg joint : retiré
        return handler

    @staticmethod
    def _anonymize_html(html: str, session, report: FileReport) -> str:
        try:
            doc = lxml.html.document_fromstring(html)
        except Exception:
            result = session.apply(html)
            report.count(result.replacements)
            return result.text
        for el in doc.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag not in HTML_SKIP and el.text:
                result = session.apply(el.text)
                if result.changed:
                    el.text = result.text
                    report.count(result.replacements)
            if el.tail:
                result = session.apply(el.tail)
                if result.changed:
                    el.tail = result.text
                    report.count(result.replacements)
            for attr in HTML_ATTRS:
                value = el.get(attr)
                if value:
                    result = session.apply(value)
                    if result.changed:
                        el.set(attr, result.text)
                        report.count(result.replacements)
            if el.tag == "img" and el.get("src", "").startswith(("http", "cid:")):
                el.set("src", "")
        return lxml.html.tostring(doc, encoding="unicode")
