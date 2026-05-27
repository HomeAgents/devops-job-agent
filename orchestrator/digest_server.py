"""Ensure the shared digest remove/status HTTP server is running (VM / orchestrator)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from orchestrator.user_db import sanitize_email


def _bootstrap_config_path() -> Path | None:
    data = Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))
    admin = os.getenv("ORCHESTRATOR_ADMIN_EMAIL", "arkadiy.kats@gmail.com").strip()
    if admin:
        p = data / "users" / sanitize_email(admin) / "config.json"
        if p.is_file():
            return p
    users = data / "users"
    if users.is_dir():
        for d in sorted(users.iterdir()):
            cfg = d / "config.json"
            if cfg.is_file():
                return cfg
    return None


def ensure_shared_remove_server() -> bool:
    """Start or verify multitenant remove server before sending digests."""
    cfg_path = _bootstrap_config_path()
    if not cfg_path:
        print("digest server: no orchestrator user config found", file=sys.stderr)
        return False
    from job_agent.digest_remove import digest_remove_enabled, ensure_remove_server_running
    from job_agent.main import load_config

    os.environ.setdefault("JOB_AGENT_CONFIG", str(cfg_path))
    cfg = load_config(cfg_path)
    if not digest_remove_enabled(cfg):
        return True
    cfg["_config_path"] = str(cfg_path)
    return ensure_remove_server_running(cfg)
