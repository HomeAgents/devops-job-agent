#!/usr/bin/env python3
"""Mark latest actionable inbox message UNSEEN for email-wake e2e test."""
from __future__ import annotations

import email
import imaplib
import os
import sys
from email.utils import parseaddr

from orchestrator.email_client import InboundMail, decode_subject
from orchestrator.email_filters import is_ignored_inbound


def main() -> int:
    user = os.getenv("GMAIL_EMAIL") or os.getenv("EMAIL_USER") or ""
    password = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASS") or ""
    if not user or not password:
        print("Missing GMAIL_EMAIL / GMAIL_APP_PASSWORD", file=sys.stderr)
        return 1
    prefer_from = (os.getenv("E2E_FROM") or "arkadiy.kats@gmail.com").lower()
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(user, password)
        imap.select("INBOX")
        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            print("Inbox empty", file=sys.stderr)
            return 1
        nums = data[0].split()
        for num in reversed(nums[-80:]):
            typ, msg_data = imap.fetch(num, "(RFC822.HEADER)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            _, addr = parseaddr(msg.get("From", ""))
            mail = InboundMail(
                message_id=msg.get("Message-ID") or "",
                from_email=addr.lower(),
                subject=decode_subject(msg.get("Subject") or ""),
                body_text="",
                attachments=[],
            )
            if is_ignored_inbound(mail):
                continue
            if prefer_from and mail.from_email != prefer_from:
                continue
            imap.store(num, "-FLAGS", "\\Seen")
            print(f"Marked UNSEEN: from={mail.from_email} subject={mail.subject!r} id={num.decode()}")
            return 0
        print(f"No actionable message from {prefer_from}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
