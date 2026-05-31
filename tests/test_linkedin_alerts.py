from __future__ import annotations

import json

from orchestrator.linkedin_alerts import (
    _home_sync_has_recent_jobs,
    _reason_indicates_session_lost,
    format_linkedin_alert_body,
    linkedin_restore_command_block,
    orchestrator_notify_email,
)


def test_reason_session_lost() -> None:
    assert _reason_indicates_session_lost("auth_wall_after_recovery")
    assert not _reason_indicates_session_lost("no_jobs_collected")


def test_notify_email_ignores_per_job_email_to(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ORCHESTRATOR_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_LINKEDIN_OWNER_EMAIL", raising=False)
    monkeypatch.setenv("EMAIL_TO", "subscriber@example.com")
    monkeypatch.setattr("orchestrator.linkedin_alerts.Path.home", lambda: tmp_path)
    assert orchestrator_notify_email() == ""


def test_notify_email_uses_admin_env(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("EMAIL_TO", "subscriber@example.com")
    assert orchestrator_notify_email() == "admin@example.com"


def test_home_sync_recent_jobs_suppresses_false_alarm(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    sync = tmp_path / "jobs.json"
    sync.write_text(
        json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "jobs": [
                    {
                        "link": "https://linkedin.com/jobs/view/1/",
                        "title": "DevOps Manager",
                        "company": "Co",
                        "location": "Israel",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = {
        "linkedin": {
            "home_sync": {"enabled": True, "import_path": str(sync), "max_age_hours": 48}
        }
    }
    assert _home_sync_has_recent_jobs(cfg)


def test_alert_body_has_exact_commands(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_LINKEDIN_OWNER_EMAIL", "arkadiy.kats@gmail.com")
    body = format_linkedin_alert_body(reason="auth_wall")
    assert "linkedin-bootstrap --email arkadiy.kats@gmail.com" in body
    assert "cd " in body and "source .venv/bin/activate" in body
    block = linkedin_restore_command_block()
    assert "run_orchestrator.py linkedin-bootstrap" in block
