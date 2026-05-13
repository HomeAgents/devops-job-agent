from __future__ import annotations

from typing import Any, Dict, List

from tenacity import retry, stop_after_attempt, wait_exponential

from job_agent.serpapi_client import serpapi_request
from job_agent.settings import get_setting


def _serpapi_key_ok() -> bool:
    k = (get_setting("SERPAPI_KEY", "GOOGLE_JOBS_API_KEY") or "").strip()
    if not k or k.lower().startswith("your_") or k.lower() in ("changeme", "xxx", "placeholder"):
        return False
    return True


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def find_contacts(company: str, role_hint: str) -> List[Dict[str, Any]]:
    if not _serpapi_key_ok():
        return []
    api_key = get_setting("SERPAPI_KEY", "GOOGLE_JOBS_API_KEY")

    queries = [
        f"{company} DevOps Manager LinkedIn",
        f"{company} Platform Engineering Manager LinkedIn",
        f"{company} recruiter DevOps LinkedIn",
        f"{company} engineering manager infrastructure LinkedIn",
    ]
    contacts: List[Dict[str, Any]] = []
    for q in queries:
        data = serpapi_request({"engine": "google", "q": q, "api_key": api_key})
        for r in (data.get("organic_results") or [])[:2]:
            link = r.get("link", "") or ""
            if "linkedin.com/in/" not in link.lower():
                continue
            contacts.append(
                {
                    "Company": company,
                    "Role Hint": role_hint,
                    "Name/Title": r.get("title", ""),
                    "Profile": link,
                    "Snippet": r.get("snippet", ""),
                }
            )

    seen: set[str] = set()
    uniq: List[Dict[str, Any]] = []
    for c in contacts:
        if c["Profile"] not in seen:
            uniq.append(c)
            seen.add(c["Profile"])
    return uniq[:5]
