"""Tests for Comeet careers API source."""

from __future__ import annotations

from unittest.mock import patch

from job_agent.models import Job
from job_agent.sources.comeet import (
    _matches_leadership_title,
    _parse_uid_from_board_url,
    fetch_comeet_company,
    resolve_comeet_credentials,
)


def test_parse_uid_from_board_url():
    assert _parse_uid_from_board_url("https://www.comeet.com/jobs/arpeely/57.001") == "57.001"


def test_matches_leadership_title():
    cfg = {"scoring": {"keywords": ["DevOps"], "seniority": ["Manager"]}}
    assert _matches_leadership_title("DevOps Engineering Manager", cfg)
    assert not _matches_leadership_title("Senior Backend Developer", cfg)


def test_fetch_comeet_company_filters_and_maps():
    cfg = {
        "comeet": {"enabled": True, "discover_credentials": False},
        "scoring": {"keywords": ["DevOps"], "seniority": ["Manager"]},
    }
    entry = {"name": "acme", "company_uid": "1.001", "token": "tok"}
    positions = [
        {
            "name": "DevOps Engineering Manager",
            "company_name": "Acme",
            "url_active_page": "https://www.comeet.com/jobs/acme/1.001/devops-manager/AB.01",
            "location": {"name": "Tel Aviv, Israel"},
            "details": [{"name": "Description", "value": "Kubernetes Terraform AWS leadership"}],
        },
        {
            "name": "Backend Developer",
            "url_active_page": "https://www.comeet.com/jobs/acme/1.001/backend/BB.01",
        },
    ]

    with patch(
        "job_agent.sources.comeet.fetch_comeet_company_positions",
        return_value=positions,
    ):
        jobs = fetch_comeet_company(entry, cfg)

    assert len(jobs) == 1
    assert jobs[0].title == "DevOps Engineering Manager"
    assert "Kubernetes" in jobs[0].raw.get("text", "")


def test_resolve_comeet_credentials_uses_cache(tmp_path):
    cache = tmp_path / "comeet_credentials.json"
    cache.write_text('{"arpeely": {"uid": "57.001", "token": "abc"}}', encoding="utf-8")
    cfg = {
        "comeet": {
            "enabled": True,
            "discover_credentials": False,
            "credentials_cache": str(cache),
        }
    }
    uid, token = resolve_comeet_credentials({"name": "arpeely"}, cfg)
    assert uid == "57.001"
    assert token == "abc"
