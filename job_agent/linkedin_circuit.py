"""LinkedIn circuit breaker: skip browser fetches after repeated failures."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_DEFAULT_MAX_FAILURES = 3
_DEFAULT_COOLDOWN_HOURS = 24


def _circuit_block(cfg: Dict[str, Any]) -> Dict[str, Any]:
    li = cfg.get("linkedin") if isinstance(cfg.get("linkedin"), dict) else {}
    block = li.get("circuit_breaker")
    return block if isinstance(block, dict) else {}


def circuit_breaker_enabled(cfg: Dict[str, Any]) -> bool:
    block = _circuit_block(cfg)
    if "enabled" in block:
        return bool(block.get("enabled"))
    return os.getenv("LINKEDIN_CIRCUIT_BREAKER", "1").strip().lower() not in ("0", "false", "no")


def _max_failures(cfg: Dict[str, Any]) -> int:
    block = _circuit_block(cfg)
    raw = block.get("max_failures") or os.getenv("LINKEDIN_CIRCUIT_MAX_FAILURES", _DEFAULT_MAX_FAILURES)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_FAILURES


def _cooldown_hours(cfg: Dict[str, Any]) -> int:
    block = _circuit_block(cfg)
    raw = block.get("cooldown_hours") or os.getenv("LINKEDIN_CIRCUIT_COOLDOWN_HOURS", _DEFAULT_COOLDOWN_HOURS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_COOLDOWN_HOURS


def circuit_state_path(cfg: Dict[str, Any]) -> Path:
    block = _circuit_block(cfg)
    explicit = (block.get("state_file") or os.getenv("LINKEDIN_CIRCUIT_STATE_FILE") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
    else:
        data = Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))
        user = str(cfg.get("_user_email") or "").strip().lower()
        if user:
            from orchestrator.user_db import sanitize_email

            p = data / "users" / sanitize_email(user) / ".linkedin-circuit.json"
        else:
            p = data / ".linkedin-circuit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _parse_ts(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def linkedin_circuit_status(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (is_open, human-readable detail)."""
    if not circuit_breaker_enabled(cfg):
        return False, ""
    path = circuit_state_path(cfg)
    state = _load_state(path)
    until = _parse_ts(str(state.get("circuit_open_until") or ""))
    if until and datetime.now(timezone.utc) < until:
        return True, until.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    if until and datetime.now(timezone.utc) >= until:
        state["circuit_open_until"] = ""
        state["alert_sent_for_open"] = False
        _save_state(path, state)
    return False, ""


def _linkedin_home_export_active() -> bool:
    return os.getenv("LINKEDIN_HOME_EXPORT", "").strip().lower() in ("1", "true", "yes")


def should_skip_linkedin_browser(cfg: Dict[str, Any]) -> bool:
    # Mac home worker must still run the browser locally.
    if _linkedin_home_export_active():
        return False
    from job_agent.linkedin_home_sync import disable_vm_linkedin_browser, home_sync_enabled

    if home_sync_enabled(cfg) and disable_vm_linkedin_browser(cfg):
        return True
    open_, _ = linkedin_circuit_status(cfg)
    return open_


def linkedin_circuit_skip_message(cfg: Dict[str, Any]) -> str:
    open_, until = linkedin_circuit_status(cfg)
    if not open_:
        return ""
    return (
        f"LinkedIn browser: skipped (circuit open until {until}; "
        "other sources still run — digest continues)"
    )


def record_linkedin_success(cfg: Dict[str, Any]) -> None:
    """Reset failure streak after a successful LinkedIn browser session."""
    note_linkedin_fetch_result(cfg, jobs_count=1)


def note_linkedin_fetch_result(
    cfg: Dict[str, Any],
    *,
    jobs_count: int,
    reason: str = "",
) -> None:
    """Record success or failure; open circuit and alert once after max_failures."""
    if not circuit_breaker_enabled(cfg):
        return
    path = circuit_state_path(cfg)
    state = _load_state(path)
    if jobs_count > 0:
        state["failure_count"] = 0
        state["circuit_open_until"] = ""
        state["alert_sent_for_open"] = False
        state["last_success_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(path, state)
        return

    failures = int(state.get("failure_count") or 0) + 1
    state["failure_count"] = failures
    state["last_failure_at"] = datetime.now(timezone.utc).isoformat()
    if reason:
        state["last_failure_reason"] = reason[:500]

    max_f = _max_failures(cfg)
    if failures >= max_f and not state.get("circuit_open_until"):
        hours = _cooldown_hours(cfg)
        until = datetime.now(timezone.utc) + timedelta(hours=hours)
        state["circuit_open_until"] = until.isoformat()
        state["alert_sent_for_open"] = False
        print(
            f"LinkedIn circuit: OPEN for {hours}h after {failures} consecutive failures "
            f"(LinkedIn optional — other job sources continue)",
            file=sys.stderr,
        )

    _save_state(path, state)

    open_, _ = linkedin_circuit_status(cfg)
    if open_ and not state.get("alert_sent_for_open"):
        from job_agent.browser.session import send_linkedin_alert_once

        try:
            from orchestrator.linkedin_alerts import format_linkedin_alert_body

            body = format_linkedin_alert_body(reason=reason or "repeated failures")
        except ImportError:
            body = ""
        send_linkedin_alert_once(cfg, reason=reason or "repeated failures", body=body)
        state = _load_state(path)
        state["alert_sent_for_open"] = True
        _save_state(path, state)
