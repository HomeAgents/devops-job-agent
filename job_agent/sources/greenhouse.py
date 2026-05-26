from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Union

import requests

from job_agent.models import Job
from job_agent.scoring import score_title, title_matches_role_focus
from job_agent.util import normalize_url, strip_html

_MAX_RETRIES = 2
_RETRY_DELAY = 3


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
        data = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                r = requests.get(url, timeout=25)
            except requests.RequestException as exc:
                print(f"Greenhouse {board}: request failed (attempt {attempt + 1}): {exc}", file=sys.stderr)
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            if r.status_code != 200:
                print(f"Greenhouse {board}: HTTP {r.status_code} (attempt {attempt + 1})", file=sys.stderr)
                if r.status_code >= 500 and attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                    continue
                break
            try:
                data = r.json()
            except ValueError:
                print(f"Greenhouse {board}: invalid JSON response", file=sys.stderr)
                break
            break
        if data is None:
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
            if not desc_text and job.get("id"):
                try:
                    jr = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job['id']}", timeout=20)
                    if jr.status_code == 200:
                        jdata = jr.json()
                        desc_text = strip_html(str(jdata.get("content", "") or ""))
                except (requests.RequestException, ValueError):
                    pass
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
