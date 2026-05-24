from __future__ import annotations

from pathlib import Path

from orchestrator.user_db import UserDB, parse_schedule_days


def test_parse_schedule_days() -> None:
    assert parse_schedule_days("daily") == list(range(7))
    assert parse_schedule_days("weekdays") == [0, 1, 2, 3, 4]
    assert 0 in parse_schedule_days("sun, mon")
    assert parse_schedule_days("each day except saturday") == [0, 1, 2, 3, 4, 5]
    assert parse_schedule_days("each day expect saturday") == [0, 1, 2, 3, 4, 5]


def test_wants_same_with_mobile_signature() -> None:
    from orchestrator.conversation import _wants_same_data

    body = "1\r\n\r\nThanks\r\n\r\nArkadiy Kats\r\narkadiy.kats@gmail.com"
    assert _wants_same_data(body)
    assert _wants_same_data("But I asked to do the same check")


def test_user_db_roundtrip(tmp_path: Path) -> None:
    db = UserDB(tmp_path / "t.db")
    u = db.get_or_create("Test@Example.com")
    assert u.email == "test@example.com"
    assert u.state == "new"
    db.update_user(u.id, keywords="devops manager", cv_path="/tmp/cv.pdf", state="scheduled", schedule_days=[0, 1])
    u2 = db.get_or_create("test@example.com")
    assert u2.keywords == "devops manager"
    due = db.users_due_today(0)
    assert any(x.email == "test@example.com" for x in due)
