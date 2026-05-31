from __future__ import annotations

from job_agent.sources.linkedin_browser import (
    build_linkedin_jobs_search_url,
    jobs_search_queries,
)


def test_jobs_search_queries_explicit_list() -> None:
    cfg = {
        "linkedin": {
            "jobs_search": {
                "multi_search": True,
                "queries": ["head of devops", "devops manager"],
                "keywords": "ignored when queries set",
            }
        }
    }
    assert jobs_search_queries(cfg) == ["head of devops", "devops manager"]


def test_jobs_search_queries_split_pipe() -> None:
    cfg = {
        "linkedin": {
            "jobs_search": {
                "multi_search": True,
                "keywords": "senior devops manager | head of devops",
            }
        }
    }
    assert jobs_search_queries(cfg) == ["senior devops manager", "head of devops"]


def test_build_url_single_phrase_quoted() -> None:
    cfg = {"linkedin": {"jobs_search": {"location": "Israel", "f_TPR": "r2592000"}}}
    url = build_linkedin_jobs_search_url(cfg, keywords="head of devops")
    assert "head+of+devops" in url or "head%20of%20devops" in url
    assert "Israel" in url or "Israel" in url
