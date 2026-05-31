"""Admin email when the shared LinkedIn session on the home Mac expires."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

SESSION_LOST_REASONS = frozenset(
    {
        "auth_wall",
        "auth_wall_after_recovery",
        "session_recovery_failed",
        "session expired",
        "2fa",
        "not logged in",
    }
)


def _reason_indicates_session_lost(reason: str) -> bool:
    low = (reason or "").lower()
    if any(r in low for r in SESSION_LOST_REASONS):
        return True
    return "auth" in low and "wall" in low


def orchestrator_notify_email() -> str:
    """Human admin inbox for LinkedIn / ops alerts (not digest EMAIL_TO / subscribers)."""
    for key in ("ORCHESTRATOR_ADMIN_EMAIL", "ORCHESTRATOR_LINKEDIN_OWNER_EMAIL"):
        v = os.getenv(key, "").strip()
        if v:
            return v
    hint = Path.home() / ".job-agent" / "linkedin-notify-email.txt"
    if hint.is_file():
        v = hint.read_text(encoding="utf-8").strip()
        if v:
            return v
    return ""


def linkedin_restore_command_block() -> str:
    from orchestrator.linkedin_shared_session import linkedin_session_owner_email

    owner = linkedin_session_owner_email().strip()
    if not owner:
        from orchestrator.linkedin_shared_session import linkedin_session_owner_safe_dir

        safe = linkedin_session_owner_safe_dir()
        if safe and "arkadiy" in safe:
            owner = "arkadiy.kats@gmail.com"
    if not owner:
        owner = "<your@gmail.com>"

    root = Path.home() / "apps/devops-job-agent"
    if not root.is_dir():
        root = Path(__file__).resolve().parent.parent

    return (
        "Run these commands on your home Mac (copy-paste):\n\n"
        f"cd {root}\n"
        "source .venv/bin/activate\n"
        f"python3 run_orchestrator.py linkedin-bootstrap --email {owner}\n\n"
        "A Chromium window opens — log in to LinkedIn, then press Enter in the terminal when done.\n"
        "Optional: sync jobs immediately after login:\n"
        f"python3 run_orchestrator.py linkedin-home-sync\n"
    )


def format_linkedin_alert_body(*, reason: str = "") -> str:
    detail = (reason or "session expired or logged out").strip()
    if _reason_indicates_session_lost(detail):
        detail = f"LinkedIn session expired or logged out ({detail})"
    lines = [
        "LinkedIn needs attention on your home Mac.",
        "Daily digests still run from Greenhouse and other sources.",
        "All orchestrator users share your LinkedIn login for job search only.",
        "",
        f"Details: {detail}",
        "",
        linkedin_restore_command_block(),
        "",
        "VM LinkedIn is disabled (Azure datacenter IP is blocked by LinkedIn).",
    ]
    return "\n".join(lines)


def maybe_alert_linkedin_session_expired(cfg: Dict[str, Any], reason: str) -> None:
    """Email admin at most once per day when home sync hits auth wall / expiry."""
    if not _reason_indicates_session_lost(reason):
        return
    path = Path.home() / ".job-agent" / ".linkedin-session-alert-sent"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if path.is_file() and path.read_text(encoding="utf-8").strip() == today:
            return
    except OSError:
        pass
    from job_agent.browser.session import send_linkedin_alert_once

    send_linkedin_alert_once(cfg, reason=reason, body=format_linkedin_alert_body(reason=reason))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(today, encoding="utf-8")
    except OSError:
        pass
