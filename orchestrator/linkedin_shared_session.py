"""One LinkedIn login on the home Mac — job search only, per-user keywords and jobs.json."""

from __future__ import annotations

import os
from pathlib import Path

from orchestrator.user_db import sanitize_email


def shared_home_linkedin_enabled() -> bool:
    """When True, all users reuse the owner LinkedIn browser session (search-only)."""
    raw = os.getenv("ORCHESTRATOR_LINKEDIN_SHARED_SESSION", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _profile_safe_dir_with_linkedin_session() -> str:
    """Pick the home-user folder that already has a LinkedIn browser session."""
    base = Path.home() / ".job-agent" / "home-users"
    if not base.is_dir():
        return ""
    best_name, best_size = "", 0
    for d in base.iterdir():
        if not d.is_dir():
            continue
        li = d / "browser" / "linkedin"
        if not li.is_dir():
            continue
        try:
            size = sum(1 for _ in li.rglob("*") if _.is_file())
        except OSError:
            size = 0
        if size > best_size:
            best_name, best_size = d.name, size
    return best_name


def linkedin_session_owner_email() -> str:
    """Account that stays logged in on the worker Mac (your LinkedIn)."""
    for key in ("ORCHESTRATOR_LINKEDIN_OWNER_EMAIL", "ORCHESTRATOR_ADMIN_EMAIL", "LINKEDIN_EMAIL"):
        v = os.getenv(key, "").strip().lower()
        if v:
            return v
    return ""


def linkedin_session_owner_safe_dir() -> str:
    """Sanitized profile dir for shared session (email or auto-detected browser data)."""
    email = linkedin_session_owner_email()
    if email:
        return sanitize_email(email)
    return _profile_safe_dir_with_linkedin_session()


def home_browser_profile_dir(subscriber_email: str) -> Path:
    """
    Browser user_data_dir for home LinkedIn export.
    Shared mode: owner's profile for every subscriber (search uses subscriber config keywords).
    """
    if shared_home_linkedin_enabled():
        safe = linkedin_session_owner_safe_dir() or sanitize_email(subscriber_email)
    else:
        safe = sanitize_email(subscriber_email)
    return Path.home() / ".job-agent" / "home-users" / safe / "browser"
