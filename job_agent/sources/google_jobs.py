from __future__ import annotations

import sys
import time
from typing import Any, Dict, List

from job_agent.models import Job
from job_agent.scoring import score_title
from job_agent.serpapi_client import serpapi_request
from job_agent.settings import get_setting
from job_agent.util import normalize_url


def _looks_configured(api_key: str) -> bool:
    if not api_key:
        return False
    low = api_key.strip().lower()
    if low.startswith("your_") or low in ("changeme", "xxx", "placeholder"):
        return False
    return True


def _serpapi_google_jobs_once(params: dict) -> dict:
    return serpapi_request(params)


def _serpapi_google_jobs_retry(params: dict) -> dict:
    last: Exception | None = None
    for attempt in range(3):
        try:
            return _serpapi_google_jobs_once(params)
        except RuntimeError as e:
            msg = str(e)
            if "401" in msg or "403" in msg or "Invalid API key" in msg:
                raise
            last = e
            if attempt < 2:
                time.sleep(min(30, 2 ** (attempt + 1)))
    assert last is not None
    raise last


def fetch_google_jobs(queries: List[str], cfg: Dict[str, Any]) -> List[Job]:
    api_key = (get_setting("SERPAPI_KEY", "GOOGLE_JOBS_API_KEY") or "").strip()
    if not _looks_configured(api_key):
        print("SerpAPI Google Jobs: skipped (set a real SERPAPI_KEY in .env)", file=sys.stderr)
        return []

    out: List[Job] = []
    seen: set[str] = set()

    for q in queries:
        params = {"engine": "google_jobs", "q": q, "api_key": api_key}
        try:
            data = _serpapi_google_jobs_retry(params)
        except RuntimeError as e:
            msg = str(e)
            if "401" in msg or "403" in msg or "Invalid API key" in msg:
                print(
                    "SerpAPI Google Jobs: invalid or unauthorized API key — skipping SerpAPI jobs.",
                    file=sys.stderr,
                )
                return []
            raise

        for job in data.get("jobs_results") or []:
            title = job.get("title", "") or ""
            opts = job.get("apply_options") or [{}]
            link = (opts[0] or {}).get("link", "") if opts else ""
            if not link:
                continue
            link_n = normalize_url(link)
            if link_n in seen:
                continue
            seen.add(link_n)
            out.append(
                Job(
                    source="serpapi_google_jobs",
                    company=job.get("company_name", "") or "",
                    title=title,
                    location=job.get("location", "") or "",
                    link=link_n,
                    posted=str((job.get("detected_extensions") or {}).get("posted_at", "recent")),
                    score=score_title(title, cfg),
                )
            )
    return out
