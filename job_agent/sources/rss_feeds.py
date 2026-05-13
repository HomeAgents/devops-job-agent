from __future__ import annotations

from typing import Any, Dict, List

import feedparser

from job_agent.models import Job
from job_agent.scoring import score_title
from job_agent.util import normalize_url


def fetch_rss_jobs(feed_urls: List[str], cfg: Dict[str, Any]) -> List[Job]:
    out: List[Job] = []
    seen: set[str] = set()

    for url in feed_urls:
        if not url or not url.startswith("http"):
            continue
        parsed = feedparser.parse(url)
        for e in parsed.entries or []:
            link = getattr(e, "link", "") or ""
            if not link:
                continue
            title = getattr(e, "title", "") or "Job"
            link_n = normalize_url(link)
            if link_n in seen:
                continue
            seen.add(link_n)
            company = ""
            if " — " in title:
                parts = title.split(" — ", 1)
                title, company = parts[0].strip(), parts[1].strip()
            posted = ""
            if getattr(e, "published", None):
                posted = str(e.published)[:32]
            out.append(
                Job(
                    source=f"rss:{url[:48]}",
                    company=company or (getattr(e, "author", "") or "Various"),
                    title=title,
                    location="Remote" if "remote" in url.lower() else "",
                    link=link_n,
                    posted=posted or "recent",
                    score=score_title(title, cfg),
                )
            )
    return out
