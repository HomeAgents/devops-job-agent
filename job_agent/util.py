from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACK = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_eid",
    "igshid",
}


def strip_html(text: str) -> str:
    """Plain text from HTML snippets (job descriptions, RSS summaries)."""
    t = html.unescape(re.sub(r"(?is)<script.*?>.*?</script>", " ", text or ""))
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_url(url: str) -> str:
    """Strip tracking query params for deduplication."""
    u = urlparse((url or "").strip())
    if not u.netloc:
        return (url or "").strip()
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in _TRACK]
    return urlunparse(u._replace(query=urlencode(q))).rstrip("/")


_LINKEDIN_JOB_ID_RE = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]+-)?(\d+)", re.I)
_GREENHOUSE_JOB_RE = re.compile(
    r"(?:boards|job-boards)(?:\.[a-z]{2,3})?\.greenhouse\.io/([^/]+)/jobs/(\d+)",
    re.I,
)
_COMEET_POSITION_RE = re.compile(
    r"comeet\.(?:co|com)/jobs/[^/]+/[^/]+/[^/]+/([^/?#]+)",
    re.I,
)


def job_link_identity(url: str) -> str:
    """
    Stable id for the same posting across URL variants
    (www vs il.linkedin.com, slug vs numeric path, etc.).
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    m = _LINKEDIN_JOB_ID_RE.search(low)
    if m:
        return f"linkedin:job:{m.group(1)}"
    gh = _GREENHOUSE_JOB_RE.search(raw)
    if gh:
        return f"greenhouse:{gh.group(1).lower()}:{gh.group(2)}"
    cm = _COMEET_POSITION_RE.search(low)
    if cm:
        return f"comeet:position:{cm.group(1)}"
    return normalize_url(raw)


def job_links_same_posting(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if normalize_url(a) == normalize_url(b):
        return True
    id_a = job_link_identity(a)
    id_b = job_link_identity(b)
    return bool(id_a) and id_a == id_b
