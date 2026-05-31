from __future__ import annotations

from orchestrator.linkedin_shared_session import (
    home_browser_profile_dir,
    linkedin_session_owner_email,
    shared_home_linkedin_enabled,
)


def test_shared_session_default_on(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_LINKEDIN_SHARED_SESSION", raising=False)
    assert shared_home_linkedin_enabled()


def test_shared_browser_dir_uses_owner(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_LINKEDIN_SHARED_SESSION", "1")
    monkeypatch.setenv("ORCHESTRATOR_LINKEDIN_OWNER_EMAIL", "owner@example.com")
    monkeypatch.delenv("EMAIL_TO", raising=False)
    p = home_browser_profile_dir("subscriber@example.com")
    assert "owner_example.com" in str(p)
    assert linkedin_session_owner_email() == "owner@example.com"


def test_per_user_browser_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_LINKEDIN_SHARED_SESSION", "0")
    p = home_browser_profile_dir("subscriber@example.com")
    assert "subscriber_example.com" in str(p)
