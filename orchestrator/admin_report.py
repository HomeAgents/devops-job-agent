"""Admin report: build text/email summaries from conversation_log."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from orchestrator.user_db import UserDB


_ADMIN_EMAIL = os.getenv("ORCHESTRATOR_ADMIN_EMAIL", "arkadiy.kats@gmail.com")

_ACTION_SHORT = {
    "welcome": "Welcome",
    "run_search": "Search",
    "keyword_review": "Keywords",
    "collect_info": "Collect",
    "admin_report": "Admin",
    "reply": "Reply",
}

_STATE_SHORT = {
    "new": "New",
    "collecting": "Collecting",
    "keyword_approval": "Keyword review",
    "ready": "Ready",
    "running": "Running",
    "scheduled": "Scheduled",
    "report_sent": "Report sent",
    "returning": "Returning",
}


def is_admin(email: str) -> bool:
    return email.strip().lower() == _ADMIN_EMAIL


def build_report(
    db: UserDB,
    *,
    days: Optional[int] = None,
    user_email: Optional[str] = None,
) -> str:
    rows = db.get_conversation_log(days=days, user_email=user_email)
    if not rows:
        period = f"last {days} days" if days else "all time"
        return f"No activity recorded ({period})."

    users = db.get_all_users()
    user_states = {u.email: u.state for u in users}

    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_user[r["user_email"]].append(r)

    now = datetime.now(timezone.utc)
    period = f"last {days} days" if days else "all history"

    lines: list[str] = []
    lines.append(f"ADMIN REPORT | {period}")
    lines.append(f"{now.strftime('%a %b %d %Y, %H:%M UTC')}")
    lines.append(f"Active users: {len(by_user)} | Total: {len(rows)} events")
    avg = _avg_reply_time(rows)
    if avg:
        lines.append(f"Avg reply time: {avg}")
    lines.append("")

    for email in sorted(by_user.keys()):
        events = by_user[email]
        state = user_states.get(email, "?")
        state_label = _STATE_SHORT.get(state, state)
        n_in = sum(1 for e in events if e["direction"] == "inbound")
        n_out = sum(1 for e in events if e["direction"] == "outbound")

        lines.append(f"{'=' * 60}")
        lines.append(f" {email}")
        lines.append(f" Status: {state_label} | In: {n_in} | Out: {n_out}")
        lines.append(f"{'=' * 60}")
        lines.append(f" {'Time':<14}| {'Dir':<4}| {'Action':<10}| Message")
        lines.append(f" {'-'*13}+{'-'*5}+{'-'*11}+{'-'*28}")

        for ev in events:
            ts = _table_ts(ev["created_at"], now)
            d = "IN" if ev["direction"] == "inbound" else "OUT"
            action = _ACTION_SHORT.get(ev.get("action") or "", "-")
            snippet = (ev.get("body_snippet") or "").replace("\n", " ").strip()
            if len(snippet) > 50:
                snippet = snippet[:47] + "..."

            lines.append(f" {ts:<14}| {d:<4}| {action:<10}| {snippet}")

            sb = ev.get("state_before")
            sa = ev.get("state_after")
            if sb and sa and sb != sa:
                sl_b = _STATE_SHORT.get(sb, sb)
                sl_a = _STATE_SHORT.get(sa, sa)
                lines.append(f" {'':14}| {'':4}| {'':10}| -> {sl_b} => {sl_a}")

        lines.append("")

    lines.append("--- End of report ---")
    return "\n".join(lines)


def _table_ts(iso: Optional[str], now: datetime) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return iso[:13]
    delta = now - dt
    if delta < timedelta(hours=24):
        return dt.strftime("%H:%M")
    if delta < timedelta(days=7):
        return dt.strftime("%a %H:%M")
    return dt.strftime("%b %d %H:%M")


def _avg_reply_time(rows: list[dict[str, Any]]) -> Optional[str]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_user[r["user_email"]].append(r)

    deltas: list[float] = []
    for events in by_user.values():
        last_in: Optional[datetime] = None
        for ev in events:
            try:
                ts = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ev["direction"] == "inbound":
                last_in = ts
            elif ev["direction"] == "outbound" and last_in:
                delta_sec = (ts - last_in).total_seconds()
                if 0 < delta_sec < 86400:
                    deltas.append(delta_sec)
                last_in = None

    if not deltas:
        return None
    avg = sum(deltas) / len(deltas)
    if avg < 60:
        return f"{int(avg)}s"
    if avg < 3600:
        return f"{int(avg / 60)} min"
    return f"{avg / 3600:.1f}h"
