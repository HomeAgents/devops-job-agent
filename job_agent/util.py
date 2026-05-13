from __future__ import annotations

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


def normalize_url(url: str) -> str:
    """Strip tracking query params for deduplication."""
    u = urlparse((url or "").strip())
    if not u.netloc:
        return (url or "").strip()
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in _TRACK]
    return urlunparse(u._replace(query=urlencode(q))).rstrip("/")
