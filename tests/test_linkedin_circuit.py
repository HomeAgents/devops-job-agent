from __future__ import annotations

from pathlib import Path

from job_agent.linkedin_circuit import (
    circuit_state_path,
    linkedin_circuit_status,
    note_linkedin_fetch_result,
    should_skip_linkedin_browser,
)


def test_vm_linkedin_skipped_when_home_sync_required() -> None:
    cfg = {"linkedin": {"home_sync": {"enabled": True, "disable_vm_linkedin_browser": True}}}
    assert should_skip_linkedin_browser(cfg)


def test_home_export_does_not_skip_browser(monkeypatch) -> None:
    cfg = {"linkedin": {"home_sync": {"enabled": True, "disable_vm_linkedin_browser": True}}}
    monkeypatch.setenv("LINKEDIN_HOME_EXPORT", "1")
    assert not should_skip_linkedin_browser(cfg)


def test_circuit_opens_after_three_failures(tmp_path: Path) -> None:
    cfg = {
        "linkedin": {
            "circuit_breaker": {
                "enabled": True,
                "max_failures": 3,
                "cooldown_hours": 24,
                "state_file": str(tmp_path / "circuit.json"),
            }
        }
    }
    for _ in range(3):
        note_linkedin_fetch_result(cfg, jobs_count=0, reason="auth_wall")
    assert should_skip_linkedin_browser(cfg)
    open_, _ = linkedin_circuit_status(cfg)
    assert open_


def test_success_resets_failures(tmp_path: Path) -> None:
    cfg = {
        "linkedin": {
            "circuit_breaker": {
                "enabled": True,
                "max_failures": 3,
                "state_file": str(tmp_path / "circuit.json"),
            }
        }
    }
    note_linkedin_fetch_result(cfg, jobs_count=0, reason="x")
    note_linkedin_fetch_result(cfg, jobs_count=0, reason="x")
    note_linkedin_fetch_result(cfg, jobs_count=5)
    assert not should_skip_linkedin_browser(cfg)
    state = __import__("json").loads(circuit_state_path(cfg).read_text())
    assert state.get("failure_count") == 0
