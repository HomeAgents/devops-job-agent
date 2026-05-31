"""Per-user LinkedIn credentials for unattended home sync (optional)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from orchestrator.user_db import UserDB, UserRecord, sanitize_email


def _parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def linkedin_env_paths(email: str) -> tuple[Path, Path, Path]:
    safe = sanitize_email(email)
    data = Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))
    root = Path(__file__).resolve().parent.parent
    return (
        data / "users" / safe / "linkedin.env",
        root / f".env.home.{safe}",
        root / ".env",
    )


def load_linkedin_env_for_user(email: str, *, meta: dict | None = None) -> Dict[str, str]:
    """
    Credentials for Playwright auto-login on the home worker Mac.
    Sources (first wins): user linkedin.env, .env.home.<safe>, user meta, project .env if email matches.
    """
    em = email.strip().lower()
    env: Dict[str, str] = {}
    user_file, home_file, project_env = linkedin_env_paths(em)
    for src in (user_file, home_file):
        for k, v in _parse_env_file(src).items():
            if v:
                env[k] = v
    block = meta or {}
    if block.get("linkedin_email"):
        env.setdefault("LINKEDIN_EMAIL", str(block["linkedin_email"]).strip())
    if block.get("linkedin_password"):
        env.setdefault("LINKEDIN_PASSWORD", str(block["linkedin_password"]).strip())
    if not env.get("LINKEDIN_EMAIL"):
        env["LINKEDIN_EMAIL"] = em
    if not env.get("LINKEDIN_PASSWORD"):
        for k, v in _parse_env_file(project_env).items():
            if k in ("LINKEDIN_EMAIL", "LINKEDIN_PASSWORD") and v:
                env[k] = v
        proj_email = env.get("LINKEDIN_EMAIL", "").strip().lower()
        if proj_email and proj_email != em:
            env.pop("LINKEDIN_PASSWORD", None)
    return {k: v for k, v in env.items() if v}


def apply_linkedin_env_for_user(email: str, *, meta: dict | None = None) -> bool:
    """Set process env for this user's LinkedIn session. Returns True if password is available."""
    for key, val in load_linkedin_env_for_user(email, meta=meta).items():
        os.environ[key] = val
    return bool(os.environ.get("LINKEDIN_PASSWORD", "").strip())


def user_record_for_email(db: UserDB, email: str) -> UserRecord | None:
    em = email.strip().lower()
    for u in db.get_all_users():
        if u.email == em:
            return u
    return None
