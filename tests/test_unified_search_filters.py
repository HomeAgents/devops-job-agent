"""Unified role + location query building across LinkedIn and Google."""

from job_agent.query_build import (
    build_unified_site_query_templates,
    or_terms_from_role_keywords,
    role_or_block,
)


def test_role_or_block_wraps_plain_or() -> None:
    assert role_or_block('"a" OR "b"') == '("a" OR "b")'
    assert role_or_block('("a" OR "b")') == '("a" OR "b")'


def test_or_terms_from_role_keywords() -> None:
    terms = or_terms_from_role_keywords('"devops manager" OR "מנהל devops" Israel')
    assert "devops manager" in terms
    assert "מנהל devops" in terms
    assert "Israel" not in terms


def test_unified_site_templates_share_role_block() -> None:
    role = '("devops manager" OR "devops director" OR "מנהל devops")'
    templates = build_unified_site_query_templates(role, "Israel", " after:2026-01-01")
    assert len(templates) == 6
    for tpl in templates:
        assert role in tpl
        assert "Israel" in tpl
    assert all("devops" in t or "מנהל" in t for t in templates)
