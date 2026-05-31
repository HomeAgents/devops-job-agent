#!/usr/bin/env python3
"""Orchestrator CLI: poll inbox, daily batch, single-user run."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from orchestrator.user_db import UserDB, sanitize_email
from orchestrator.vm_lifecycle import ensure_vm_started, maybe_stop_vm, touch_activity


def _db() -> UserDB:
    path = os.getenv("ORCHESTRATOR_DB", str(data_root() / "orchestrator.db"))
    return UserDB(path)


def _acquire_poll_lock() -> "open | None":
    """Prevent concurrent poll-inbox executions via exclusive file lock."""
    lock_path = data_root() / ".poll-inbox.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lf = open(lock_path, "w")
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lf
    except OSError:
        return None


def _recover_stuck_users(db: UserDB, max_running_minutes: int = 30) -> int:
    """Reset users stuck in 'running' state for too long."""
    from datetime import timedelta, timezone as tz

    cutoff = (datetime.now(tz.utc) - timedelta(minutes=max_running_minutes)).isoformat()
    recovered = 0
    for user in db.get_all_users():
        if user.state != "running":
            continue
        changed = user.last_outbound_at or user.last_inbound_at
        if changed and changed < cutoff:
            print(f"Recovering stuck user {user.email} (in 'running' since {changed})")
            db.update_user(user.id, state="returning")
            recovered += 1
    return recovered


def cmd_poll(args: argparse.Namespace) -> int:
    lock = _acquire_poll_lock()
    if lock is None:
        print("Another poll-inbox is already running — skipping.")
        return 0

    try:
        db = _db()
        recovered = _recover_stuck_users(db)
        if recovered:
            print(f"Recovered {recovered} stuck user(s) from 'running' state.")

        engine = ConversationEngine(db)
        mails = fetch_inbound(max_messages=args.max, known_message_ids=db.known_message_ids())
        did_work = False
        for mail in mails:
            if is_ignored_inbound(mail):
                why = ignore_reason(mail) or "filtered"
                print(f"Skipped from={mail.from_email} subject={mail.subject!r} ({why})")
                continue
            print(f"Processing from={mail.from_email} subject={mail.subject!r}")
            engine.handle(mail)
            did_work = True
        retried = engine.retry_unreplied(min_age_seconds=120, max_retries=3)
        if retried:
            print(f"Retried {retried} unreplied message(s).")
            did_work = True
        sent = engine.send_feedback_prompts(minutes_after=args.feedback_minutes)
        if sent:
            print(f"Sent {sent} feedback prompt(s).")
            did_work = True
        if did_work:
            touch_activity()
        if not args.no_autostop:
            if maybe_stop_vm(args.idle_minutes):
                print(f"VM deallocate requested (idle >= {args.idle_minutes} min).")
    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        except OSError:
            pass
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    ensure_vm_started()
    touch_activity()
    try:
        from orchestrator.digest_server import ensure_shared_remove_server

        ensure_shared_remove_server()
    except Exception as exc:
        print(f"digest remove server check failed: {exc}", file=sys.stderr)
    tz = ZoneInfo(os.getenv("ORCHESTRATOR_TZ", "Asia/Jerusalem"))
    now = datetime.now(tz)
    weekday = (now.weekday() + 1) % 7  # Sun=0
    db = _db()

    cleanup_days = int(os.getenv("ORCHESTRATOR_CLEANUP_DAYS", "7"))
    if cleanup_days > 0:
        try:
            from orchestrator.email_client import cleanup_mailbox
            results = cleanup_mailbox(max_age_days=cleanup_days)
            total = sum(results.values())
            if total:
                print(f"Mailbox cleanup: deleted {total} message(s) older than {cleanup_days} days")
        except Exception as exc:
            print(f"Mailbox cleanup failed: {exc}", file=sys.stderr)

    users = db.users_due_today(weekday)
    print(f"Daily run {now.isoformat()} weekday={weekday} users={len(users)}")
    max_parallel = int(os.getenv("ORCHESTRATOR_MAX_PARALLEL", "3"))
    errors = 0

    def _run_one(user):
        try:
            print(f"  -> {user.email}")
            db.update_user(user.id, state="running")
            return user.email, run_docker_job(user, db)
        except Exception as exc:
            print(f"  !! {user.email} failed: {exc}", file=sys.stderr)
            return user.email, 1

    if len(users) <= 1 or max_parallel <= 1:
        for user in users:
            _, rc = _run_one(user)
            if rc != 0:
                errors += 1
    else:
        with ThreadPoolExecutor(max_workers=min(max_parallel, len(users))) as pool:
            futures = {pool.submit(_run_one, u): u for u in users}
            for fut in as_completed(futures):
                email, rc = fut.result()
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


def cmd_admin_report(args: argparse.Namespace) -> int:
    from orchestrator.admin_report import build_report

    db = _db()
    days = args.days if args.days and args.days > 0 else None
    user_email = args.user if args.user else None
    report = build_report(db, days=days, user_email=user_email)
    print(report)
    return 0


def cmd_linkedin_home_sync(_args: argparse.Namespace) -> int:
    """Run home LinkedIn export for every orchestrator user (home worker Mac)."""
    import subprocess

    script = _ROOT / "scripts" / "linkedin-home-workers-all.sh"
    if not script.is_file():
        print(f"Missing {script}", file=sys.stderr)
        return 1
    proc = subprocess.run(["/bin/bash", str(script)], cwd=str(_ROOT))
    return int(proc.returncode)


def cmd_linkedin_bootstrap(args: argparse.Namespace) -> int:
    """Admin: open browser once to save LinkedIn session for a user (home worker profile)."""
    from orchestrator.job_runner import build_user_config, project_root as root
    from orchestrator.linkedin_credentials import apply_linkedin_env_for_user

    db = _db()
    user = db.get_or_create(args.email)
    base = Path(os.getenv("ORCHESTRATOR_BASE_CONFIG", str(root() / "config.json")))
    if not base.is_file():
        base = root() / "config.browser.example.json"
    cfg_path = build_user_config(user, base)
    from orchestrator.linkedin_shared_session import (
        home_browser_profile_dir,
        linkedin_session_owner_email,
        shared_home_linkedin_enabled,
    )

    owner = linkedin_session_owner_email() if shared_home_linkedin_enabled() else user.email
    if not owner:
        owner = user.email
    browser = home_browser_profile_dir(user.email)
    browser.mkdir(parents=True, exist_ok=True)
    ou = db.get_or_create(owner)
    apply_linkedin_env_for_user(owner, meta=ou.meta)
    safe = sanitize_email(user.email)

    import json

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("browser", {})["user_data_dir"] = str(browser)
    tmp = Path(f"/tmp/job-agent-bootstrap-{safe}.json")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.environ["JOB_AGENT_CONFIG"] = str(tmp)
    from job_agent.browser.session import open_linkedin_login

    ok = open_linkedin_login(cfg, wait_minutes=max(1, int(args.wait_minutes)))
    if ok:
        notify = Path.home() / ".job-agent" / "linkedin-notify-email.txt"
        try:
            notify.parent.mkdir(parents=True, exist_ok=True)
            notify.write_text(owner.strip().lower() + "\n", encoding="utf-8")
        except OSError:
            pass
    return 0 if ok else 1


def cmd_cleanup_mailbox(args: argparse.Namespace) -> int:
    from orchestrator.email_client import cleanup_mailbox

    results = cleanup_mailbox(max_age_days=args.days, dry_run=args.dry_run)
    total = sum(results.values())
    if args.dry_run:
        print(f"Dry run: would delete {total} message(s) total")
    else:
        print(f"Deleted {total} message(s) total")
    for folder, count in results.items():
        print(f"  {folder}: {count}")
    return 0


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

    p_report = sub.add_parser("admin-report", help="Print admin conversation report")
    p_report.add_argument("--days", type=int, default=0, help="Limit to last N days (0=all)")
    p_report.add_argument("--user", type=str, default="", help="Filter by user email")
    p_report.set_defaults(func=cmd_admin_report)

    p_li = sub.add_parser("linkedin-home-sync", help="Home Mac: sync LinkedIn for all orchestrator users")
    p_li.set_defaults(func=cmd_linkedin_home_sync)

    p_boot = sub.add_parser("linkedin-bootstrap", help="Admin: manual LinkedIn login for one user (home profile)")
    p_boot.add_argument("--email", required=True)
    p_boot.add_argument("--wait-minutes", type=int, default=10)
    p_boot.set_defaults(func=cmd_linkedin_bootstrap)

    p_clean = sub.add_parser("cleanup-mailbox", help="Delete old emails from Gmail folders")
    p_clean.add_argument("--days", type=int, default=7, help="Delete emails older than N days (default 7)")
    p_clean.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    p_clean.set_defaults(func=cmd_cleanup_mailbox)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
