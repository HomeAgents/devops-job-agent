"""LinkedIn Posts (hiring announcements) via logged-in browser (Playwright)."""

from __future__ import annotations

import random
import re
import sys
import time
from typing import Any, Dict, List
from urllib.parse import quote_plus


def _jittered_sleep(base: float, jitter_fraction: float = 0.3) -> None:
    delta = base * jitter_fraction
    time.sleep(base + random.uniform(-delta, delta))

from job_agent.browser.session import playwright_available, with_linkedin_context
from job_agent.linkedin_og import hiring_signal_in_text, matches_leadership_role_focus
from job_agent.models import Job
from job_agent.scoring import score_title
from job_agent.util import normalize_url


def _posts_search_block(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("linkedin", {})
    ps = block.get("posts_search") if isinstance(block, dict) else None
    return ps if isinstance(ps, dict) else {}


def _build_posts_search_url(cfg: Dict[str, Any]) -> str:
    ps = _posts_search_block(cfg)
    keywords = (ps.get("keywords") or "").strip()
    if not keywords:
        js = cfg.get("linkedin", {})
        if isinstance(js, dict):
            jobs_search = js.get("jobs_search")
            if isinstance(jobs_search, dict):
                role_kw = (jobs_search.get("keywords") or "").strip()
                if role_kw:
                    keywords = f"{role_kw} hiring"
    if not keywords:
        keywords = '"devops manager" hiring Israel'
    return f"https://www.linkedin.com/search/results/content/?keywords={quote_plus(keywords)}&origin=GLOBAL_SEARCH_HEADER"


_POST_LINK_RE = re.compile(r"https://www\.linkedin\.com/(?:posts/|feed/update/)[^\s\"'<>]+")
_HIRING_TITLE_RE = re.compile(
    r"^(.+?)\s+(?:hiring|is hiring|are hiring)\s+(.+?)(?:\s+in\s+(.+?))?$",
    re.I,
)


_EXTRACT_POSTS_JS = """
() => {
  const posts = [];
  const seen = new Set();
  const items = document.querySelectorAll(
    'div.feed-shared-update-v2, div[data-urn], div.update-components-actor'
  );
  const containers = items.length > 0
    ? items
    : document.querySelectorAll('[class*="search-results"] li, [class*="reusable-search"] li');

  for (const el of containers) {
    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!text) continue;

    // Find post permalink
    let postUrl = '';
    const timeLink = el.querySelector('a[href*="/feed/update/"], a[href*="/posts/"]');
    if (timeLink) {
      postUrl = (timeLink.href || timeLink.getAttribute('href') || '').split('?')[0];
    }
    if (!postUrl) {
      const allLinks = el.querySelectorAll('a[href]');
      for (const a of allLinks) {
        const h = a.href || a.getAttribute('href') || '';
        if (/\\/posts\\/|feed\\/update\\//.test(h)) {
          postUrl = h.split('?')[0];
          break;
        }
      }
    }
    if (!postUrl || seen.has(postUrl)) continue;
    seen.add(postUrl);

    // Extract author
    let author = '';
    const actorEl = el.querySelector(
      '[class*="actor-name"], [class*="update-components-actor__name"] span[aria-hidden="true"], ' +
      'span.feed-shared-actor__name span[aria-hidden="true"]'
    );
    if (actorEl) author = (actorEl.innerText || '').trim();

    // Extract job links from within the post
    const jobLinks = [];
    const jobAnchors = el.querySelectorAll('a[href*="/jobs/view/"]');
    for (const a of jobAnchors) {
      const h = (a.href || a.getAttribute('href') || '').split('?')[0];
      if (h) jobLinks.push(h);
    }

    posts.push({
      postUrl,
      author,
      text: text.substring(0, 800),
      jobLinks,
    });
  }
  return posts;
}
"""


def fetch_linkedin_posts(cfg: Dict[str, Any]) -> List[Job]:
    """Search LinkedIn content feed for hiring posts."""
    li = cfg.get("linkedin")
    if not isinstance(li, dict) or not li.get("enabled", True):
        return []
    ps = _posts_search_block(cfg)
    if not ps.get("enabled", True):
        return []
    if not playwright_available():
        return []

    search_url = _build_posts_search_url(cfg)
    max_scrolls = int(ps.get("max_scrolls", 3))
    scroll_pause = float(ps.get("scroll_pause_seconds", 2.0))
    require_hiring = ps.get("require_hiring_signal", True)
    require_role = ps.get("filter_by_role_focus", True)

    print(f"LinkedIn posts: opening {search_url}", file=sys.stderr)

    out: List[Job] = []
    seen_links: set[str] = set()

    with with_linkedin_context(cfg) as (pw, context):
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_selector(
                'div.feed-shared-update-v2, div[data-urn], [class*="reusable-search"] li',
                timeout=20_000,
            )
        except Exception:
            pass
        _jittered_sleep(4.0)

        url_low = (page.url or "").lower()
        if "authwall" in url_low or "uas/login" in url_low:
            print("LinkedIn posts: not logged in (auth wall)", file=sys.stderr)
            return []

        for scroll_idx in range(max_scrolls):
            if scroll_idx > 0:
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                _jittered_sleep(scroll_pause)

        _jittered_sleep(2.0)
        raw_posts = page.evaluate(_EXTRACT_POSTS_JS)
        if not isinstance(raw_posts, list):
            raw_posts = []

        for post in raw_posts:
            if not isinstance(post, dict):
                continue
            text = str(post.get("text") or "")
            post_url = str(post.get("postUrl") or "")
            author = str(post.get("author") or "")
            job_links = post.get("jobLinks") or []

            if require_hiring and not hiring_signal_in_text(text):
                continue
            if require_role and not matches_leadership_role_focus(text, cfg):
                continue

            if job_links:
                for jl in job_links:
                    link_n = normalize_url(jl.split("?")[0])
                    if link_n in seen_links:
                        continue
                    seen_links.add(link_n)
                    title_match = re.search(
                        r"(?:hiring|looking for|open (?:role|position))[:\s]+([^\n.!]+)",
                        text, re.I,
                    )
                    title = title_match.group(1).strip()[:120] if title_match else "Hiring (from post)"
                    out.append(Job(
                        source="linkedin_posts_browser",
                        company=author or "Unknown",
                        title=title,
                        location="Israel",
                        link=link_n,
                        posted="recent",
                        score=score_title(title, cfg),
                        raw={
                            "post_url": post_url,
                            "text": text[:500],
                            "author": author,
                        },
                    ))
            else:
                if post_url in seen_links:
                    continue
                seen_links.add(post_url)
                title_match = re.search(
                    r"(?:hiring|looking for|open (?:role|position))[:\s]+([^\n.!]+)",
                    text, re.I,
                )
                title = title_match.group(1).strip()[:120] if title_match else "Hiring announcement"
                out.append(Job(
                    source="linkedin_posts_browser",
                    company=author or "Unknown",
                    title=title,
                    location="Israel",
                    link=post_url,
                    posted="recent",
                    score=score_title(title, cfg),
                    raw={
                        "post_url": post_url,
                        "text": text[:500],
                        "author": author,
                    },
                ))

        print(f"LinkedIn posts: collected {len(out)} hiring post(s)", file=sys.stderr)

    return out
