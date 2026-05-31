from __future__ import annotations

from pathlib import Path

from orchestrator.linkedin_credentials import load_linkedin_env_for_user
from orchestrator.linkedin_home_users import linkedin_home_sync_enabled_for_user, users_for_home_linkedin_sync
from orchestrator.user_db import UserDB, UserRecord


def test_users_for_home_linkedin_sync_from_db(tmp_path: Path) -> None:
    db = UserDB(tmp_path / "t.db")
    u1 = db.get_or_create("active@example.com")
    db.update_user(u1.id, state="scheduled", keywords="devops manager", schedule_days=[0, 1])
    u2 = db.get_or_create("paused@example.com")
    db.update_user(u2.id, state="scheduled", keywords="pm", schedule_days=[])
    u3 = db.get_or_create("new@example.com")
    assert u3.state == "new"
    emails = users_for_home_linkedin_sync(db)
    assert "active@example.com" in emails
    assert "paused@example.com" in emails
    assert "new@example.com" not in emails


def test_linkedin_opt_out_meta() -> None:
    u = UserRecord(
        id=1,
        email="x@y.com",
        state="scheduled",
        cv_path=None,
        keywords="devops",
        schedule_days=[1],
        schedule_time="09:00",
        timezone="Asia/Jerusalem",
        last_inbound_at=None,
        last_outbound_at=None,
        report_sent_at=None,
        feedback_sent_at=None,
        pending_feedback=False,
        meta={"linkedin_home_sync_enabled": False},
    )
    assert not linkedin_home_sync_enabled_for_user(u)


def test_load_linkedin_env_defaults_email(tmp_path: Path) -> None:
    env = load_linkedin_env_for_user("Someone@Example.com")
    assert env["LINKEDIN_EMAIL"] == "someone@example.com"
