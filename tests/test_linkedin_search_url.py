"""LinkedIn Jobs search URL and orchestrator keyword → query mapping."""

import json
import os
from urllib.parse import parse_qs, unquote_plus, urlparse

from job_agent.sources.linkedin_browser import build_linkedin_jobs_search_url
from orchestrator.job_runner import build_user_config
from orchestrator.keyword_review import (
    build_keyword_review,
    build_linkedin_query,
    normalize_linkedin_keywords,
)
from orchestrator.user_db import UserRecord


def test_build_linkedin_query_en_and_hebrew_or() -> None:
    review = build_keyword_review("DevOps Manager OR DevOps Director Israel")
    q = build_linkedin_query(review.options, "Israel")
    assert "devops manager" in q.lower()
    assert " OR " in q
    assert "Israel" not in q
    assert any("\u0590" <= ch <= "\u05ff" for ch in q)


def test_normalize_linkedin_keywords_strips_location() -> None:
    raw = '("devops manager" OR "devops director") Israel'
    assert normalize_linkedin_keywords(raw, location="Israel") == (
        '("devops manager" OR "devops director")'
    )


def test_build_linkedin_jobs_search_url_mixed_or() -> None:
    cfg = {
        "linkedin": {
            "jobs_search": {
                "keywords": '"devops manager" OR "devops director" OR "מנהל devops"',
                "location": "Israel",
            }
        }
    }
    url = build_linkedin_jobs_search_url(cfg)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    kw = unquote_plus(params["keywords"][0])
    loc = unquote_plus(params["location"][0])
    assert "devops manager" in kw
    assert "מנהל devops" in kw
    assert " OR " in kw
    assert loc == "Israel"
    assert parsed.path.endswith("/jobs/search/")


def test_build_user_config_syncs_linkedin_and_ats(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_DATA_DIR", str(tmp_path / "data"))
    base = tmp_path / "config.json"
    base.write_text(
        json.dumps(
            {
                "linkedin": {"jobs_search": {"keywords": "old", "location": "Israel"}},
                "ats_google_site_search": {"enabled": True, "role_phrases": ['("old")']},
                "location_hint": "Israel",
            }
        ),
        encoding="utf-8",
    )
    user = UserRecord(
        id=1,
        email="test@example.com",
        state="report_sent",
        cv_path=None,
        keywords=None,
        schedule_days=[],
        schedule_time="09:00",
        timezone="Asia/Jerusalem",
        last_inbound_at=None,
        last_outbound_at=None,
        report_sent_at=None,
        feedback_sent_at=None,
        pending_feedback=False,
        meta={
            "approved_keyword_query": '"devops manager" OR "מנהל devops" Israel',
            "location_hint": "Israel",
        },
    )
    out = build_user_config(user, base)
    cfg = json.loads(out.read_text(encoding="utf-8"))
    assert cfg["linkedin"]["jobs_search"]["keywords"] == '"devops manager" OR "מנהל devops"'
    assert cfg["linkedin"]["jobs_search"]["location"] == "Israel"
    assert cfg["ats_google_site_search"]["role_phrases"] == ['("devops manager" OR "מנהל devops")']
    assert cfg["ats_google_site_search"]["prepend_builtin_devops_or_blocks"] is False
    assert "devops manager" in cfg["ats_google_site_search"]["extra_query_templates"][-1]
    assert cfg["scoring"]["keywords"] == ["devops manager", "מנהל devops"]
