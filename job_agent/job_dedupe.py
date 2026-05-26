"""Collapse duplicate postings in digest lists (URL variants + cross-source)."""

from __future__ import annotations

import re
from typing import Dict, List

from job_agent.models import Job
from job_agent.network import companies_match, normalize_company
from job_agent.util import job_link_identity, job_links_same_posting, normalize_url


def normalize_job_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).casefold()


def job_title_company_key(title: str, company: str) -> tuple[str, str]:
    """Canonical (title, company) pair for same-posting comparison."""
    return normalize_job_title(title), normalize_company(company)


def _link_dedupe_key(link: str) -> str:
    raw = (link or "").strip()
    if not raw:
        return ""
    return job_link_identity(raw) or normalize_url(raw)


def _pick_better_job(a: Job, b: Job) -> Job:
    return a if (a.score, a.title) >= (b.score, b.title) else b


def jobs_same_posting(a: Job, b: Job) -> bool:
    """Same role at the same employer, including cross-platform URL duplicates."""
    if job_links_same_posting(a.link or "", b.link or ""):
        return True
    title_a, title_b = normalize_job_title(a.title), normalize_job_title(b.title)
    if not title_a or not title_b or title_a != title_b:
        return False
    if not (a.company or "").strip() or not (b.company or "").strip():
        return False
    if job_title_company_key(a.title, a.company) == job_title_company_key(b.title, b.company):
        return True
    return companies_match(a.company, b.company)


def dedupe_jobs(jobs: List[Job]) -> List[Job]:
    """One row per posting: link identity, then matching title + company."""
    if not jobs:
        return []

    by_link: Dict[str, Job] = {}
    no_link: List[Job] = []
    for job in jobs:
        key = _link_dedupe_key(job.link)
        if not key:
            no_link.append(job)
            continue
        prev = by_link.get(key)
        by_link[key] = job if prev is None else _pick_better_job(job, prev)

    kept: List[Job] = []
    tc_index: Dict[tuple[str, str], int] = {}
    for job in list(by_link.values()) + no_link:
        tc_key = job_title_company_key(job.title, job.company)
        if tc_key[0] and tc_key[1]:
            idx = tc_index.get(tc_key)
            if idx is not None:
                kept[idx] = _pick_better_job(job, kept[idx])
                continue
        merged = False
        for i, prev in enumerate(kept):
            if jobs_same_posting(job, prev):
                kept[i] = _pick_better_job(job, prev)
                tc_prev = job_title_company_key(prev.title, prev.company)
                if tc_prev[0] and tc_prev[1]:
                    tc_index[tc_prev] = i
                tc_new = job_title_company_key(kept[i].title, kept[i].company)
                if tc_new[0] and tc_new[1]:
                    tc_index[tc_new] = i
                merged = True
                break
        if not merged:
            new_idx = len(kept)
            kept.append(job)
            if tc_key[0] and tc_key[1]:
                tc_index[tc_key] = new_idx

    return sorted(kept, key=lambda x: (-x.score, x.title))
