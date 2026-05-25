from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_WEEKDAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_email(email: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", email.strip().lower())


@dataclass
class UserRecord:
    id: int
    email: str
    state: str
    cv_path: Optional[str]
    keywords: Optional[str]
    schedule_days: list[int]
    schedule_time: str
    timezone: str
    last_inbound_at: Optional[str]
    last_outbound_at: Optional[str]
    report_sent_at: Optional[str]
    feedback_sent_at: Optional[str]
    pending_feedback: bool
    meta: dict[str, Any]


class UserDB:
    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL UNIQUE,
                  state TEXT NOT NULL DEFAULT 'new',
                  cv_path TEXT,
                  keywords TEXT,
                  schedule_days TEXT NOT NULL DEFAULT '[]',
                  schedule_time TEXT NOT NULL DEFAULT '09:00',
                  timezone TEXT NOT NULL DEFAULT 'Asia/Jerusalem',
                  last_inbound_at TEXT,
                  last_outbound_at TEXT,
                  report_sent_at TEXT,
                  feedback_sent_at TEXT,
                  pending_feedback INTEGER NOT NULL DEFAULT 0,
                  meta_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS searches (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  label TEXT NOT NULL DEFAULT 'default',
                  keywords TEXT NOT NULL,
                  cv_path TEXT,
                  active INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS inbound_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id TEXT NOT NULL UNIQUE,
                  from_email TEXT NOT NULL,
                  subject TEXT,
                  received_at TEXT NOT NULL,
                  reply_status TEXT NOT NULL DEFAULT 'pending',
                  retry_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversation_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  direction TEXT NOT NULL,
                  user_email TEXT NOT NULL,
                  subject TEXT,
                  body_snippet TEXT,
                  action TEXT,
                  state_before TEXT,
                  state_after TEXT,
                  message_id TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            # Migration: add reply_status/retry_count to existing inbound_log tables
            try:
                conn.execute("ALTER TABLE inbound_log ADD COLUMN reply_status TEXT NOT NULL DEFAULT 'replied'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE inbound_log ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    def _row_to_user(self, row: sqlite3.Row) -> UserRecord:
        days_raw = row["schedule_days"] or "[]"
        try:
            days = json.loads(days_raw)
        except json.JSONDecodeError:
            days = []
        if not isinstance(days, list):
            days = []
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return UserRecord(
            id=row["id"],
            email=row["email"],
            state=row["state"],
            cv_path=row["cv_path"],
            keywords=row["keywords"],
            schedule_days=[int(d) for d in days if (isinstance(d, int) or str(d).isdigit())],
            schedule_time=row["schedule_time"] or "09:00",
            timezone=row["timezone"] or "Asia/Jerusalem",
            last_inbound_at=row["last_inbound_at"],
            last_outbound_at=row["last_outbound_at"],
            report_sent_at=row["report_sent_at"],
            feedback_sent_at=row["feedback_sent_at"],
            pending_feedback=bool(row["pending_feedback"]),
            meta=meta if isinstance(meta, dict) else {},
        )

    def get_or_create(self, email: str) -> UserRecord:
        email = email.strip().lower()
        now = _utc_now()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                return self._row_to_user(row)
            conn.execute(
                """
                INSERT INTO users (email, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (email, now, now),
            )
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return self._row_to_user(row)

    def update_user(
        self,
        user_id: int,
        *,
        state: Optional[str] = None,
        cv_path: Optional[str] = None,
        keywords: Optional[str] = None,
        schedule_days: Optional[list[int]] = None,
        schedule_time: Optional[str] = None,
        last_inbound_at: Optional[str] = None,
        last_outbound_at: Optional[str] = None,
        report_sent_at: Optional[str] = None,
        feedback_sent_at: Optional[str] = None,
        pending_feedback: Optional[bool] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if state is not None:
            fields.append("state = ?")
            values.append(state)
        if cv_path is not None:
            fields.append("cv_path = ?")
            values.append(cv_path)
        if keywords is not None:
            fields.append("keywords = ?")
            values.append(keywords)
        if schedule_days is not None:
            fields.append("schedule_days = ?")
            values.append(json.dumps(schedule_days))
        if schedule_time is not None:
            fields.append("schedule_time = ?")
            values.append(schedule_time)
        if last_inbound_at is not None:
            fields.append("last_inbound_at = ?")
            values.append(last_inbound_at)
        if last_outbound_at is not None:
            fields.append("last_outbound_at = ?")
            values.append(last_outbound_at)
        if report_sent_at is not None:
            fields.append("report_sent_at = ?")
            values.append(report_sent_at)
        if feedback_sent_at is not None:
            fields.append("feedback_sent_at = ?")
            values.append(feedback_sent_at)
        if pending_feedback is not None:
            fields.append("pending_feedback = ?")
            values.append(1 if pending_feedback else 0)
        if meta is not None:
            fields.append("meta_json = ?")
            values.append(json.dumps(meta))
        fields.append("updated_at = ?")
        values.append(_utc_now())
        values.append(user_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)

    def users_due_today(self, weekday: int) -> list[UserRecord]:
        """weekday: 0=Sunday … 6=Saturday (datetime.weekday()+1 % 7 for Sun=0)."""
        out: list[UserRecord] = []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE state IN ('scheduled', 'ready', 'returning')"
            ).fetchall()
        for row in rows:
            user = self._row_to_user(row)
            if not user.schedule_days:
                continue
            if weekday in user.schedule_days:
                out.append(user)
        return out

    def users_needing_feedback(self, minutes_after_report: int = 30) -> list[UserRecord]:
        out: list[UserRecord] = []
        cutoff = datetime.now(timezone.utc)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE pending_feedback = 1 AND report_sent_at IS NOT NULL
                """
            ).fetchall()
        for row in rows:
            user = self._row_to_user(row)
            try:
                sent = datetime.fromisoformat(user.report_sent_at.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            delta_min = (cutoff - sent).total_seconds() / 60
            if delta_min >= minutes_after_report and not user.feedback_sent_at:
                out.append(user)
        return out

    def known_message_ids(self, lookback_days: int = 30) -> set[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT message_id FROM inbound_log WHERE received_at >= ? OR received_at IS NULL",
                (cutoff,),
            ).fetchall()
        return {str(r[0]) for r in rows if r[0]}

    def log_inbound(self, message_id: str, from_email: str, subject: str) -> bool:
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO inbound_log (message_id, from_email, subject, received_at, reply_status, retry_count)
                    VALUES (?, ?, ?, ?, 'pending', 0)
                    """,
                    (message_id, from_email, subject, _utc_now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def mark_replied(self, message_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE inbound_log SET reply_status = 'replied' WHERE message_id = ?",
                (message_id,),
            )

    def get_unreplied(self, min_age_seconds: int = 120, max_retries: int = 3) -> list[dict[str, Any]]:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, from_email, subject, received_at, retry_count
                FROM inbound_log
                WHERE reply_status = 'pending' AND retry_count < ? AND received_at <= ?
                ORDER BY received_at ASC
                """,
                (max_retries, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    def increment_retry(self, message_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE inbound_log SET retry_count = retry_count + 1 WHERE message_id = ?",
                (message_id,),
            )

    def mark_dead_letter(self, message_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE inbound_log SET reply_status = 'dead_letter' WHERE message_id = ?",
                (message_id,),
            )

    def add_search(self, user_id: int, keywords: str, cv_path: Optional[str], label: str = "default") -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO searches (user_id, label, keywords, cv_path, active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (user_id, label, keywords, cv_path, now),
            )

    def list_searches(self, user_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, label, keywords, cv_path, active FROM searches WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def log_conversation(
        self,
        *,
        direction: str,
        user_email: str,
        subject: Optional[str] = None,
        body_snippet: Optional[str] = None,
        action: Optional[str] = None,
        state_before: Optional[str] = None,
        state_after: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        snippet = (body_snippet or "")[:200]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_log
                  (direction, user_email, subject, body_snippet, action, state_before, state_after, message_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (direction, user_email, subject, snippet, action, state_before, state_after, message_id, _utc_now()),
            )

    def get_conversation_log(
        self,
        *,
        days: Optional[int] = None,
        user_email: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_email:
            clauses.append("user_email = ?")
            params.append(user_email.strip().lower())
        if days and days > 0:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            clauses.append("created_at >= ?")
            params.append(cutoff)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM conversation_log {where} ORDER BY created_at ASC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_users(self) -> list[UserRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY email").fetchall()
        return [self._row_to_user(r) for r in rows]


def parse_schedule_days(text: str) -> list[int]:
    t = text.strip().lower()
    if not t:
        return []
    exclude: set[int] = set()
    m = re.search(r"(?:except|excluding|but not|without|expect)\s+(\w+)", t)
    if m:
        word = m.group(1)
        for i, name in enumerate(_WEEKDAY_NAMES):
            if word.startswith(name[:3]) or name.startswith(word[:3]):
                exclude.add(i)
        if any(p in t for p in ("daily", "each day", "every day", "כל יום")):
            return [d for d in range(7) if d not in exclude]
    if t in ("daily", "every day", "כל יום") or any(p in t for p in ("each day", "every day")):
        return list(range(7))
    if t in ("weekdays", "weekday", "sun-thu", "א-ה"):
        return [0, 1, 2, 3, 4]
    days: list[int] = []
    for part in re.split(r"[\s,;/]+", t):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            n = int(part)
            if 0 <= n <= 6:
                days.append(n)
            continue
        for i, name in enumerate(_WEEKDAY_NAMES):
            if part.startswith(name[:3]):
                days.append(i)
                break
    return sorted(set(days))
