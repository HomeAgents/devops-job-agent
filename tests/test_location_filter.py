from job_agent.location_filter import filter_jobs_by_location_hint
from job_agent.models import Job


def _cfg() -> dict:
    return {
        "location_hint": "Israel",
        "filter_jobs_by_location_hint": True,
        "location_filter_mode": "israel_or_il_signals",
        "location_hint_aliases": ["israel", "tel aviv", "ישראל"],
        "location_filter_source_prefixes": ["linkedin_browser", "linkedin_home_sync"],
    }


def test_linkedin_us_location_dropped() -> None:
    jobs = [
        Job(
            "linkedin_browser",
            "CrowdStrike",
            "DevOps Director",
            "United States",
            "https://www.linkedin.com/jobs/view/1/",
            raw={"search_url": "https://www.linkedin.com/jobs/search/?location=Israel"},
        ),
        Job(
            "linkedin_browser",
            "Nice",
            "DevOps Manager",
            "Tel Aviv, Israel",
            "https://www.linkedin.com/jobs/view/2/",
            raw={"search_url": "https://www.linkedin.com/jobs/search/?location=Israel"},
        ),
    ]
    out = filter_jobs_by_location_hint(jobs, _cfg())
    assert len(out) == 1
    assert out[0].company == "Nice"


def test_linkedin_home_sync_same_rules() -> None:
    jobs = [
        Job(
            "linkedin_home_sync",
            "AWS",
            "Director",
            "United Kingdom",
            "https://www.linkedin.com/jobs/view/3/",
            raw={"_home_sync": True},
        ),
    ]
    out = filter_jobs_by_location_hint(jobs, _cfg())
    assert len(out) == 0
