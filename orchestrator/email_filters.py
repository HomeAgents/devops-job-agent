"""Skip other agents and system mail on the shared genie4cv@gmail.com inbox."""

from __future__ import annotations

import os
import re
from typing import Iterable

from orchestrator.email_client import InboundMail, decode_subject

# Outbound agent mail is skipped via from_addr == own mailbox (genie4cv).
# Do not filter "[Birthday Copilot]" by subject — user approval replies keep that subject
# and must wake the VM for birthday-copilot IMAP polling.
_DEFAULT_IGNORE_SUBJECT_PATTERNS: tuple[str, ...] = (
    r"\[scoutsignal\]",
    r"\bscoutsignal\s+report\b",
    r"delivery status notification",
    r"mail delivery subsystem",
    r"security alert",
)

_DEFAULT_IGNORE_FROM_LOCALPARTS: tuple[str, ...] = (
    "mailer-daemon",
    "postmaster",
    "noreply",
    "no-reply",
    "donotreply",
)


def _own_mailbox() -> str:
    return (
        os.getenv("ORCHESTRATOR_SMTP_USER")
        or os.getenv("ORCHESTRATOR_IMAP_USER")
        or os.getenv("GMAIL_EMAIL")
        or os.getenv("EMAIL_USER")
        or os.getenv("EMAIL_TO")
        or ""
    ).strip().lower()


def _extra_subject_patterns() -> list[re.Pattern[str]]:
    raw = os.getenv("ORCHESTRATOR_IGNORE_SUBJECT_REGEX", "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[re.Pattern[str]] = []
    for part in parts:
        try:
            out.append(re.compile(part, re.I))
        except re.error:
            continue
    return out


def _compiled_default_subject_patterns() -> list[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in _DEFAULT_IGNORE_SUBJECT_PATTERNS]


def ignore_reason(mail: InboundMail) -> str | None:
    """Return a short reason if this message should not run the job orchestrator."""
    from_addr = (mail.from_email or "").strip().lower()
    own = _own_mailbox()
    if own and from_addr == own:
        return "sent from orchestrator mailbox (other agent or self)"

    if from_addr.endswith("@accounts.google.com"):
        return "google system mail"

    local = from_addr.split("@", 1)[0]
    if any(local == p or local.startswith(p + "+") for p in _DEFAULT_IGNORE_FROM_LOCALPARTS):
        return "system sender"

    subject = decode_subject(mail.subject or "")
    subj_lower = subject.lower()
    for pat in _compiled_default_subject_patterns():
        if pat.search(subj_lower):
            return f"subject matches agent/system filter ({pat.pattern})"
    for pat in _extra_subject_patterns():
        if pat.search(subject):
            return f"subject matches ORCHESTRATOR_IGNORE_SUBJECT_REGEX"

    return None


def is_ignored_inbound(mail: InboundMail) -> bool:
    return ignore_reason(mail) is not None


def filter_job_orchestrator_mail(mails: Iterable[InboundMail]) -> list[InboundMail]:
    return [m for m in mails if not is_ignored_inbound(m)]
