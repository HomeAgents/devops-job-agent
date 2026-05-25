from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Optional


@dataclass
class InboundMail:
    message_id: str
    from_email: str
    subject: str
    body_text: str
    attachments: list[tuple[str, bytes]]
    references: str = ""


def _smtp_settings() -> tuple[str, str, str, str]:
    user = (
        os.getenv("ORCHESTRATOR_SMTP_USER")
        or os.getenv("GMAIL_EMAIL")
        or os.getenv("EMAIL_USER")
        or ""
    )
    password = (
        os.getenv("ORCHESTRATOR_SMTP_PASSWORD")
        or os.getenv("GMAIL_APP_PASSWORD")
        or os.getenv("EMAIL_PASS")
        or ""
    )
    from_name = os.getenv("ORCHESTRATOR_FROM_NAME", "Job Assistant")
    if not user or not password:
        raise RuntimeError("Missing ORCHESTRATOR_SMTP_USER / ORCHESTRATOR_SMTP_PASSWORD (or GMAIL_* / EMAIL_*).")
    return user, password, from_name, user


def _imap_settings() -> tuple[str, str]:
    user = (
        os.getenv("ORCHESTRATOR_IMAP_USER")
        or os.getenv("ORCHESTRATOR_SMTP_USER")
        or os.getenv("GMAIL_EMAIL")
        or os.getenv("EMAIL_USER")
        or ""
    )
    password = (
        os.getenv("ORCHESTRATOR_IMAP_PASSWORD")
        or os.getenv("ORCHESTRATOR_SMTP_PASSWORD")
        or os.getenv("GMAIL_APP_PASSWORD")
        or os.getenv("EMAIL_PASS")
        or ""
    )
    if not user or not password:
        raise RuntimeError("Missing IMAP credentials (ORCHESTRATOR_IMAP_* or GMAIL_*).")
    return user, password


def _clean_header(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


def decode_subject(raw: str) -> str:
    if not raw:
        return "Job assistance"
    cleaned = _clean_header(raw)
    try:
        parts = decode_header(cleaned)
        return _clean_header(str(make_header(parts)))
    except (email.errors.HeaderParseError, UnicodeError, ValueError):
        return cleaned


def reply_subject(original: str) -> str:
    base = decode_subject(original)
    base = re.sub(r"^(re:\s*)+", "", base, flags=re.I).strip()
    return f"Re: {base or 'Job assistance'}"


def send_reply(
    to_email: str,
    subject: str,
    body: str,
    *,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> str:
    """Send a plain-text reply in the user's thread. Returns outbound Message-ID."""
    smtp_user, smtp_pass, from_name, from_addr = _smtp_settings()
    msg = EmailMessage()
    msg["Subject"] = _clean_header(reply_subject(subject))
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_email
    outbound_id = make_msgid(domain=from_addr.split("@")[-1] if "@" in from_addr else None)
    msg["Message-ID"] = outbound_id
    if in_reply_to:
        clean_reply_to = _clean_header(in_reply_to)
        msg["In-Reply-To"] = clean_reply_to
        ref_chain = _clean_header(references or "")
        if ref_chain and clean_reply_to not in ref_chain:
            msg["References"] = f"{ref_chain} {clean_reply_to}"
        else:
            msg["References"] = ref_chain or clean_reply_to
    msg.set_content(body.strip() + "\n")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
    return outbound_id


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_text(msg: email.message.Message) -> str:
    plain: list[str] = []
    html: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            chunk = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                plain.append(chunk)
            elif ctype == "text/html":
                html.append(chunk)
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        chunk = payload.decode(charset, errors="replace")
        if msg.get_content_type() == "text/html":
            html.append(chunk)
        else:
            plain.append(chunk)
    parts = plain if plain else [_html_to_text(h) for h in html]
    text = "\n".join(parts).strip()
    text = re.split(r"\nOn .+ wrote:\n|\n-----Original Message-----", text, maxsplit=1)[0]
    return text.strip()


def _extract_attachments(msg: email.message.Message) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    if not msg.is_multipart():
        return out
    seen: set[tuple[str, int]] = set()
    for part in msg.walk():
        disp = str(part.get("Content-Disposition", "")).lower()
        ctype = (part.get_content_type() or "").lower()
        name = part.get_filename() or ""
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        is_file = "attachment" in disp
        is_inline_cv = (
            "inline" in disp
            and name.lower().endswith((".pdf", ".doc", ".docx", ".txt"))
        )
        is_typed_cv = ctype in (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        ) and bool(name)
        if not (is_file or is_inline_cv or is_typed_cv):
            continue
        fname = name or "attachment.bin"
        key = (fname.lower(), len(payload))
        if key in seen:
            continue
        seen.add(key)
        out.append((fname, payload))
    return out


def fetch_unseen(max_messages: int = 20) -> list[InboundMail]:
    """Backward-compatible wrapper."""
    return fetch_inbound(max_messages=max_messages)


def fetch_inbound(
    max_messages: int = 20,
    *,
    known_message_ids: set[str] | None = None,
    since_days: int = 7,
) -> list[InboundMail]:
    """Fetch UNSEEN mail plus recent INBOX messages not yet in inbound_log.

    Gmail often marks messages read in the web UI before the VM polls; without the
    second pass those emails would never be processed.
    """
    from datetime import datetime, timedelta, timezone

    known = known_message_ids or set()
    imap_user, imap_pass = _imap_settings()
    host = os.getenv("ORCHESTRATOR_IMAP_HOST", "imap.gmail.com")
    mails: list[InboundMail] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(imap_user, imap_pass)
        imap.select("INBOX")

        unseen_ids: set[bytes] = set()
        typ, data = imap.search(None, "UNSEEN")
        if typ == "OK" and data and data[0]:
            unseen_ids = set(data[0].split())

        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = imap.search(None, f"(SINCE {since})")
        recent_ids: list[bytes] = []
        if typ == "OK" and data and data[0]:
            recent_ids = data[0].split()

        # Union unseen + recent; keep chronological order (oldest first).
        ordered: list[bytes] = []
        seen_nums: set[bytes] = set()
        for num in recent_ids:
            if num not in seen_nums:
                ordered.append(num)
                seen_nums.add(num)
        for num in unseen_ids:
            if num not in seen_nums:
                ordered.append(num)
                seen_nums.add(num)

        candidates = ordered[-max_messages:]
        for num in candidates:
            typ, msg_data = imap.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            _, addr = parseaddr(msg.get("From", ""))
            message_id = _clean_header(msg.get("Message-ID") or f"local-{num.decode()}")
            if message_id in known:
                continue
            subject = decode_subject(msg.get("Subject") or "")
            body = _extract_text(msg)
            attachments = _extract_attachments(msg)
            references = _clean_header(msg.get("References") or "")
            if not addr:
                continue
            mails.append(
                InboundMail(
                    message_id=message_id,
                    from_email=addr.lower(),
                    subject=subject,
                    body_text=body,
                    attachments=attachments,
                    references=references,
                )
            )
            if num in unseen_ids:
                imap.store(num, "+FLAGS", "\\Seen")
    return mails
