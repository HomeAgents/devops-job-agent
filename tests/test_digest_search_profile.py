import pandas as pd

from job_agent.digest_search_profile import (
    build_search_profile_df,
    build_search_profile_rows,
    build_search_profile_with_fetch_stats_df,
)


def test_search_profile_includes_linkedin_and_scoring():
    cfg = {
        "location_hint": "Israel",
        "location_hint_aliases": ["tel aviv", "hybrid"],
        "linkedin": {
            "jobs_search": {
                "keywords": "devops manager OR sre manager",
                "location": "Israel",
            }
        },
        "role_focus": ["DevOps Manager"],
        "scoring": {"keywords": ["DevOps", "SRE"], "seniority": ["Manager"]},
        "greenhouse_boards": ["nice"],
        "google_web_browser": {"enabled": False},
        "ats_google_site_search": {"enabled": False},
    }
    rows = build_search_profile_rows(cfg)
    scopes = [r[0] for r in rows]
    assert any("LinkedIn" in s for s in scopes)
    assert any("Title keywords" in s for s in scopes)
    assert any("Greenhouse" in s for s in scopes)
    df = build_search_profile_df(cfg)
    assert list(df.columns) == ["Scope", "Keywords"]
    assert len(df) >= 4


def test_search_profile_includes_comeet_when_enabled():
    cfg = {
        "location_hint": "Israel",
        "comeet": {
            "enabled": True,
            "companies": [{"name": "arpeely", "board_url": "https://www.comeet.com/jobs/arpeely/57.001"}],
        },
        "google_web_browser": {"enabled": False},
        "ats_google_site_search": {"enabled": False},
    }
    rows = build_search_profile_rows(cfg)
    comeet = [r for r in rows if r[0] == "Comeet companies"]
    assert len(comeet) == 1
    assert "arpeely" in comeet[0][1]
    assert "DevOps" in comeet[0][1]


def test_merge_fetch_stats_unique_added():
    cfg = {
        "location_hint": "Israel",
        "linkedin": {
            "jobs_search": {"keywords": "devops", "location": "Israel"},
        },
        "greenhouse_boards": ["nice", "taboola"],
        "google_web_browser": {"enabled": False},
        "ats_google_site_search": {"enabled": False},
    }
    stats = pd.DataFrame(
        [
            {"Site": "LinkedIn (browser)", "Fetched": 28, "Unique added": 28},
            {"Site": "Greenhouse: nice", "Fetched": 5, "Unique added": 5},
            {"Site": "Greenhouse: taboola", "Fetched": 0, "Unique added": 0},
        ]
    )
    merged = build_search_profile_with_fetch_stats_df(cfg, stats)
    assert "Unique added" in merged.columns
    li = merged[merged["Scope"].str.startswith("LinkedIn")].iloc[0]
    assert li["Unique added"] == "28"
    gh = merged[merged["Scope"] == "Greenhouse boards"].iloc[0]
    assert gh["Unique added"] == "5"
    loc = merged[merged["Scope"] == "Location filter"].iloc[0]
    assert loc["Unique added"] == "—"


def test_merge_comeet_fetch_stats_not_duplicated():
    cfg = {
        "location_hint": "Israel",
        "comeet": {"enabled": True, "companies": [{"name": "arpeely"}]},
        "google_web_browser": {"enabled": False},
        "ats_google_site_search": {"enabled": False},
    }
    stats = pd.DataFrame([{"Site": "Comeet: arpeely", "Fetched": 8, "Unique added": 0}])
    merged = build_search_profile_with_fetch_stats_df(cfg, stats)
    comeet_rows = merged[merged["Scope"].str.contains("Comeet", na=False)]
    assert len(comeet_rows) == 1
    assert comeet_rows.iloc[0]["Keywords"] != "—"
    assert comeet_rows.iloc[0]["Unique added"] == "0"
