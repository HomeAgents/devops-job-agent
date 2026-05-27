from __future__ import annotations

import json
from pathlib import Path

from job_agent.linkedin_home_sync import (
    apply_fast_vm_overrides_when_home_sync_fresh,
    disable_vm_linkedin_browser,
    export_linkedin_jobs,
    load_home_sync_jobs,
    load_home_sync_jobs_stale_fallback,
    resolve_linkedin_home_sync,
)
from job_agent.models import Job


def test_home_sync_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    jobs = [
        Job(
            source="linkedin_browser",
            company="Acme",
            title="DevOps Manager",
            location="Israel",
            link="https://www.linkedin.com/jobs/view/123/",
            score=5,
        )
    ]
    export_linkedin_jobs(path, jobs)
    cfg = {
        "_user_email": "test@example.com",
        "linkedin": {
            "home_sync": {
                "enabled": True,
                "import_path": str(path),
                "max_age_hours": 24,
            }
        },
    }
    loaded, msg = load_home_sync_jobs(cfg)
    assert len(loaded) == 1
    assert loaded[0].link.endswith("/123/")
    assert "home sync" in msg
    payload = json.loads(path.read_text())
    assert payload["count"] == 1
    assert loaded[0].raw.get("_home_sync") is True


def test_fast_vm_overrides_when_fresh(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    export_linkedin_jobs(path, [])
    cfg = {
        "_user_email": "test@example.com",
        "linkedin": {
            "home_sync": {
                "enabled": True,
                "import_path": str(path),
                "max_age_hours": 24,
            }
        },
        "google_web_browser": {"enabled": True},
    }
    fast = apply_fast_vm_overrides_when_home_sync_fresh(cfg)
    assert fast["linkedin"]["jobs_search"]["scrape_reach_out_people"] is False
    assert fast["google_web_browser"]["enabled"] is False


def test_stale_fallback_loads_older_file(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    export_linkedin_jobs(
        path,
        [
            Job(
                source="linkedin_browser",
                company="Co",
                title="Lead",
                location="Tel Aviv",
                link="https://www.linkedin.com/jobs/view/9/",
                score=1,
            )
        ],
    )
    import os
    import time

    old = time.time() - 25 * 3600
    os.utime(path, (old, old))
    cfg = {
        "_user_email": "t@example.com",
        "linkedin": {
            "home_sync": {
                "enabled": True,
                "import_path": str(path),
                "max_age_hours": 18,
                "stale_fallback_hours": 36,
            }
        },
    }
    fresh, _ = load_home_sync_jobs(cfg)
    assert len(fresh) == 0
    stale, msg = load_home_sync_jobs_stale_fallback(cfg)
    assert len(stale) == 1
    assert "stale fallback" in msg
    jobs, _, skip = resolve_linkedin_home_sync(cfg)
    assert skip is True
    assert len(jobs) == 1


def test_disable_vm_when_home_sync_on() -> None:
    cfg = {"linkedin": {"home_sync": {"enabled": True}}}
    assert disable_vm_linkedin_browser(cfg) is True
