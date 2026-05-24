#!/usr/bin/env python3
"""Resend keyword approval email to a user (same thread). Usage: resend-approval.py user@example.com"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / "orchestrator.env", override=False)
load_dotenv(_ROOT / ".env", override=False)

from orchestrator.email_client import send_reply
from orchestrator.keyword_review import (
    KeywordReview,
    build_keyword_review,
    clean_keywords_input,
    format_approval_email,
)
from orchestrator.user_db import UserDB


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: resend-approval.py email@example.com", file=sys.stderr)
        return 1
    email = sys.argv[1].strip().lower()
    db_path = os.getenv("ORCHESTRATOR_DB", str(Path.home() / "orchestrator-data/orchestrator.db"))
    db = UserDB(db_path)
    user = db.get_or_create(email)
    cleaned = clean_keywords_input(user.keywords or "")
    review = build_keyword_review(cleaned)
    if not review.options:
        print(f"No keyword review for {email}", file=sys.stderr)
        return 1
    meta = dict(user.meta)
    meta.update(review.to_meta())
    body = format_approval_email(review)
    subject = meta.get("thread_subject") or "Job assistance"
    in_reply_to = meta.get("thread_last_inbound_id") or meta.get("thread_last_outbound_id")
    references = meta.get("thread_references")
    outbound = send_reply(email, subject, body, in_reply_to=in_reply_to, references=references)
    refs = [r for r in (references or "").split() if r]
    if outbound not in refs:
        refs.append(outbound)
    meta["thread_references"] = " ".join(refs[-30:])
    meta["thread_last_outbound_id"] = outbound
    db.update_user(user.id, state="keyword_approval", keywords=cleaned, meta=meta)
    print(f"Sent keyword approval to {email} ({len(review.options)} phrases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
