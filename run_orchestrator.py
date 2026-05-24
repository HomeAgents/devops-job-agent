#!/usr/bin/env python3
"""Orchestrator CLI: poll inbox, daily batch, single-user run."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / "orchestrator.env", override=False)

from orchestrator.conversation import ConversationEngine
from orchestrator.email_client import fetch_inbound
from orchestrator.email_filters import ignore_reason, is_ignored_inbound
from orchestrator.job_runner import data_root, run_docker_job, run_job_for_user
from orchestrator.user_db import UserDB
from orchestrator.vm_lifecycle import ensure_vm_started, maybe_stop_vm, touch_activity


def _db() -> UserDB:
    path = os.getenv("ORCHESTRATOR_DB", str(data_root() / "orchestrator.db"))
    return UserDB(path)


def cmd_poll(args: argparse.Namespace) -> int:
    ensure_vm_started()
    touch_activity()
    db = _db()
    engine = ConversationEngine(db)
    mails = fetch_inbound(max_messages=args.max, known_message_ids=db.known_message_ids())
    for mail in mails:
        if is_ignored_inbound(mail):
            why = ignore_reason(mail) or "filtered"
            print(f"Skipped from={mail.from_email} subject={mail.subject!r} ({why})")
            continue
        print(f"Processing from={mail.from_email} subject={mail.subject!r}")
        engine.handle(mail)
    sent = engine.send_feedback_prompts(minutes_after=args.feedback_minutes)
    if sent:
        print(f"Sent {sent} feedback prompt(s).")
    if not args.no_autostop:
        if maybe_stop_vm(args.idle_minutes):
            print(f"VM deallocate requested (idle >= {args.idle_minutes} min).")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    ensure_vm_started()
    touch_activity()
    tz = ZoneInfo(os.getenv("ORCHESTRATOR_TZ", "Asia/Jerusalem"))
    now = datetime.now(tz)
    weekday = (now.weekday() + 1) % 7  # Sun=0
    db = _db()
    users = db.users_due_today(weekday)
    print(f"Daily run {now.isoformat()} weekday={weekday} users={len(users)}")
    errors = 0
    for user in users:
        print(f"  -> {user.email}")
        rc = run_docker_job(user, db)
        if rc != 0:
            errors += 1
    touch_activity()
    return 1 if errors else 0


def cmd_run_user(args: argparse.Namespace) -> int:
    ensure_vm_started()
    touch_activity()
    db = _db()
    user = db.get_or_create(args.email)
    rc = run_docker_job(user, db) if not args.dry_run else run_job_for_user(user, db, dry_run=True)
    touch_activity()
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Job agent email orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_poll = sub.add_parser("poll-inbox", help="Fetch unseen mail and reply / trigger jobs")
    p_poll.add_argument("--max", type=int, default=20)
    p_poll.add_argument("--feedback-minutes", type=int, default=30)
    p_poll.add_argument("--idle-minutes", type=int, default=15)
    p_poll.add_argument("--no-autostop", action="store_true", help="Do not deallocate VM when idle")
    p_poll.set_defaults(func=cmd_poll)

    p_daily = sub.add_parser("daily", help="Run scheduled searches for today (9:00 batch)")
    p_daily.set_defaults(func=cmd_daily)

    p_user = sub.add_parser("run-user", help="Run job agent for one email profile")
    p_user.add_argument("--email", required=True)
    p_user.add_argument("--dry-run", action="store_true")
    p_user.set_defaults(func=cmd_run_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
