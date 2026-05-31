"""Which orchestrator users get automatic home LinkedIn sync on the worker Mac."""

from __future__ import annotations

import os
from typing import List

from orchestrator.user_db import UserDB, UserRecord

# Users with keywords who may receive digests — sync LinkedIn for all unless opted out.
_ACTIVE_STATES = frozenset({"scheduled", "report_sent", "ready", "returning"})


def linkedin_home_sync_enabled_for_user(user: UserRecord) -> bool:
    meta = user.meta if isinstance(user.meta, dict) else {}
    if meta.get("linkedin_home_sync_enabled") is False:
        return False
    if meta.get("linkedin_disabled") is True:
        return False
    return bool((user.keywords or "").strip())


def users_for_home_linkedin_sync(db: UserDB | None = None) -> List[str]:
    """Emails to process on the home Mac (cron / orchestrator). No manual USER_EMAILS list."""
    if db is None:
        path = os.getenv("ORCHESTRATOR_DB", str(os.path.expanduser("~/orchestrator-data/orchestrator.db")))
        db = UserDB(path)
    emails: List[str] = []
    for user in db.get_all_users():
        if user.state not in _ACTIVE_STATES:
            continue
        if not linkedin_home_sync_enabled_for_user(user):
            continue
        emails.append(user.email)
    return sorted(set(emails))
