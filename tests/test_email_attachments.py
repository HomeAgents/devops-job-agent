from __future__ import annotations

import email
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from orchestrator.email_client import _extract_attachments


def test_extract_inline_pdf() -> None:
    msg = MIMEMultipart()
    msg.attach(MIMEText("Program Manager Israel"))
    part = MIMEApplication(b"%PDF-1.4 test", _subtype="pdf")
    part.add_header(
        "Content-Disposition",
        'inline; filename="CV Amnon Meron SPgM Eng Apr 2026.pdf"',
    )
    msg.attach(part)
    raw = msg.as_bytes()
    parsed = email.message_from_bytes(raw)
    atts = _extract_attachments(parsed)
    assert len(atts) == 1
    assert atts[0][0].endswith(".pdf")
    assert atts[0][1].startswith(b"%PDF")
