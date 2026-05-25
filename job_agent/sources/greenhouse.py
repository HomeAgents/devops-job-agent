from __future__ import annotations

from typing import Any, Dict, List, Union

import requests

from job_agent.models import Job
from job_agent.scoring import score_title, title_matches_role_focus
from job_agent.util import normalize_url, strip_html


def _greenhouse_location(job: Dict[str, Any]) -> str:
    """Human-readable location from Greenhouse job JSON (often multiple offices)."""
    raw_loc = job.get("location")
    if isinstance(raw_loc, str) and raw_loc.strip():
        return raw_loc.strip()
    if isinstance(raw_loc, dict):
        n = (raw_loc.get("name") or "").strip()
        if n:
            return n
    offices: Union[List[Any], Dict[str, Any], None] = job.get("offices")
    names: List[str] = []
    if isinstance(offices, dict):
        offices = [offices]
    if isinstance(offices, list):
        for item in offices:
            if isinstance(item, dict):
                nm = (item.get("name") or "").strip()
                if nm:
                    names.append(nm)
            elif item:
                names.append(str(item).strip())
    if names:
        seen: set[str] = set()
        uniq = []
        for n in names:
            low = n.lower()
            if low not in seen:
                seen.add(low)
                uniq.append(n)
        return " • ".join(uniq)
    return ""


def fetch_greenhouse(boards: List[str], cfg: Dict[str, Any]) -> List[Job]:
    out: List[Job] = []
    seen: set[str] = set()

    for board in boards:
        board = (board or "").strip().strip("/")
        if not board:
            continue
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        try:
            r = requests.get(url, timeout=25)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        company = (data.get("name") or board).replace(" Job Board", "").strip()
        for job in data.get("jobs") or []:
            title = job.get("title", "") or ""
            if not title:
                continue
            if not title_matches_role_focus(title, cfg):
                continue
            link = job.get("absolute_url") or ""
            if not link:
                continue
            link_n = normalize_url(link)
            if link_n in seen:
                continue
            seen.add(link_n)
            loc = _greenhouse_location(job)
            updated = str(job.get("updated_at", "") or "").strip()
            posted = updated if updated else "recent"
            desc_text = strip_html(str(job.get("content", "") or ""))
            out.append(
                Job(
                    source=f"greenhouse:{board}",
                    company=company,
                    title=title,
                    location=loc,
                    link=link_n,
                    posted=posted,
                    score=score_title(title, cfg),
                    raw={"text": desc_text},
                )
            )
    return out
