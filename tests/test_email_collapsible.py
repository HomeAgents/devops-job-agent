"""Collapsible digest email sections."""

from __future__ import annotations

import pandas as pd

from job_agent.excel_email import (
    _build_digest_html,
    _wrap_email_collapsible_section,
    digest_email_collapsible_enabled,
    digest_email_section_open,
)


def test_collapsible_disabled_uses_heading():
    cfg = {"digest_email_collapsible_tables": {"enabled": False}}
    html = _wrap_email_collapsible_section("Jobs", "<table></table>", cfg, section="jobs")
    assert "<h2" in html
    assert "<details" not in html


def test_collapsible_enabled_uses_details():
    cfg = {
        "digest_email_collapsible_tables": {
            "enabled": True,
            "sections": {"jobs": True, "removed": False},
        }
    }
    assert digest_email_collapsible_enabled(cfg)
    assert digest_email_section_open(cfg, "jobs") is True
    assert digest_email_section_open(cfg, "removed") is False
    open_html = _wrap_email_collapsible_section("Jobs", "<table></table>", cfg, section="jobs")
    assert "<details" in open_html and " open" in open_html
    closed_html = _wrap_email_collapsible_section(
        "Removed", "<table></table>", cfg, section="removed", default_open=False
    )
    assert "<details" in closed_html
    assert " open" not in closed_html.split(">")[0]


def test_build_digest_html_jobs_collapsible():
    cfg = {
        "digest_email_collapsible_tables": {"enabled": True, "sections": {"jobs": True}},
        "digest_remove": {"enabled": False},
    }
    df = pd.DataFrame(
        [
            {
                "Job Title": "DevOps Manager",
                "Company": "Acme",
                "Network": "",
                "Link": "https://example.com/j/1",
                "Source": "test",
                "Location": "Israel",
            }
        ]
    )
    html = _build_digest_html(df, pd.DataFrame(), pd.DataFrame(), cfg, pd.DataFrame(), pd.DataFrame())
    assert "<details" in html
    assert "Jobs in this digest" in html
