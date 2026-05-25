"""Fetch jobs from Comeet public Careers API (per-company uid + token)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from job_agent.models import Job
from job_agent.scoring import score_title
from job_agent.util import normalize_url, strip_html

_COMEET_API = "https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
_BOARD_UID_RE = re.compile(r"comeet\.(?:co|com)/jobs/[^/]+/([0-9A-F.]+)", re.I)
_CRED_RE = re.compile(r"company-uid=([0-9A-F.]+).*?token=([^&\s\"']+)", re.I)
_DEFAULT_CACHE = Path.home() / ".job-agent" / "comeet_credentials.json"


def comeet_enabled(cfg: Dict[str, Any]) -> bool:
    block = cfg.get("comeet")
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled"))


def _comeet_block(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("comeet")
    return block if isinstance(block, dict) else {}


def _cache_path(cfg: Dict[str, Any]) -> Path:
    raw = str(_comeet_block(cfg).get("credentials_cache") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _DEFAULT_CACHE


def _load_cache(cfg: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    path = _cache_path(cfg)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cfg: Dict[str, Any], cache: Dict[str, Dict[str, str]]) -> None:
    path = _cache_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _company_key(entry: Dict[str, Any]) -> str:
    return str(entry.get("name") or entry.get("slug") or entry.get("board_url") or "").strip().lower()


def _parse_uid_from_board_url(board_url: str) -> str:
    m = _BOARD_UID_RE.search(board_url or "")
    return m.group(1) if m else ""


def _comeet_location(position: Dict[str, Any]) -> str:
    loc = position.get("location")
    if isinstance(loc, dict):
        return str(loc.get("name") or "").strip()
    if isinstance(loc, str):
        return loc.strip()
    return ""


def _comeet_description(position: Dict[str, Any]) -> str:
    parts: List[str] = []
    for block in position.get("details") or []:
        if not isinstance(block, dict):
            continue
        val = str(block.get("value") or "").strip()
        if val:
            parts.append(strip_html(val))
    return "\n\n".join(parts)


def _matches_leadership_title(title: str, cfg: Dict[str, Any]) -> bool:
    tlow = (title or "").lower()
    if not tlow:
        return False
    role_signals = (
        "devops",
        "site reliability",
        " sre",
        "sre ",
        "sre,",
        "sre/",
        "infrastructure",
        "infra ",
        "platform engineering",
        "platform engineer",
        "head of platform",
        "director of platform",
        "vp of platform",
        "engineering manager",
        "engineering lead",
        "cloud infrastructure",
        "kubernetes",
        "terraform",
    )
    if not any(x in tlow for x in role_signals):
        return False
    if not any(x in tlow for x in ("manager", "director", "head", "lead", "vp", "vice")):
        return False
    return True


def discover_comeet_credentials_playwright(board_url: str, cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Open Comeet careers board in browser; capture uid/token from network."""
    try:
        from job_agent.browser.session import playwright_available, with_google_context
    except ImportError:
        return "", ""
    if not playwright_available():
        return "", ""

    uid = _parse_uid_from_board_url(board_url)
    token = ""
    discovered_uid = ""

    with with_google_context(cfg) as (pw, ctx):
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        creds: Dict[str, str] = {}

        def on_response(resp: Any) -> None:
            nonlocal discovered_uid, token
            m = _CRED_RE.search(resp.url or "")
            if m:
                discovered_uid, token = m.group(1), m.group(2)
                creds["uid"], creds["token"] = discovered_uid, token

        page.on("response", on_response)
        page.goto(board_url, wait_until="networkidle", timeout=120_000)
        time.sleep(float(_comeet_block(cfg).get("discover_wait_seconds") or 6))
        if creds.get("uid"):
            discovered_uid = creds["uid"]
        if creds.get("token"):
            token = creds["token"]

    return discovered_uid or uid, token


def resolve_comeet_credentials(entry: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[str, str]:
    uid = str(entry.get("company_uid") or entry.get("uid") or "").strip()
    token = str(entry.get("token") or "").strip()
    board_url = str(entry.get("board_url") or entry.get("careers_url") or "").strip()
    if not uid and board_url:
        uid = _parse_uid_from_board_url(board_url)

    key = _company_key(entry)
    cache = _load_cache(cfg)
    cached = cache.get(key) if key else None
    if isinstance(cached, dict):
        uid = uid or str(cached.get("uid") or "").strip()
        token = token or str(cached.get("token") or "").strip()

    if (not uid or not token) and board_url and _comeet_block(cfg).get("discover_credentials", True):
        d_uid, d_token = discover_comeet_credentials_playwright(board_url, cfg)
        uid = uid or d_uid
        token = token or d_token
        if key and uid and token:
            cache[key] = {"uid": uid, "token": token, "board_url": board_url}
            _save_cache(cfg, cache)

    return uid, token


def fetch_comeet_company_positions(
    entry: Dict[str, Any],
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    uid, token = resolve_comeet_credentials(entry, cfg)
    if not uid or not token:
        return []
    try:
        r = requests.get(
            _COMEET_API.format(uid=uid),
            params={"token": token, "details": "true"},
            timeout=int(_comeet_block(cfg).get("timeout_seconds") or 30),
        )
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("positions") or [])
    return []


def fetch_comeet_company(entry: Dict[str, Any], cfg: Dict[str, Any]) -> List[Job]:
    name = str(entry.get("name") or entry.get("slug") or "Comeet").strip()
    positions = fetch_comeet_company_positions(entry, cfg)
    out: List[Job] = []
    seen: set[str] = set()

    for position in positions:
        if not isinstance(position, dict):
            continue
        title = str(position.get("name") or "").strip()
        if not title or not _matches_leadership_title(title, cfg):
            continue
        link = (
            str(position.get("url_active_page") or "")
            or str(position.get("url_recruit_hosted_page") or "")
            or str(position.get("position_url") or "")
        ).strip()
        if not link:
            continue
        link_n = normalize_url(link)
        if link_n in seen:
            continue
        seen.add(link_n)
        company = str(position.get("company_name") or name).strip() or name
        loc = _comeet_location(position)
        desc = _comeet_description(position)
        updated = str(position.get("time_updated") or position.get("time_last_updated") or "").strip()
        out.append(
            Job(
                source=f"comeet:{name}",
                company=company,
                title=title,
                location=loc,
                link=link_n,
                posted=updated if updated else "recent",
                score=score_title(title, cfg),
                raw={"text": desc, "comeet_uid": str(position.get("uid") or "")},
            )
        )
    return out


def fetch_comeet_job_description_http(link: str, *, raw: Optional[Dict[str, Any]] = None) -> str:
    """Description for CV fit: use stored raw text or best-effort from careers page."""
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("description") or "").strip()
        if len(text) >= 80:
            return text
    low = (link or "").lower()
    if "comeet" not in low:
        return ""
    try:
        import requests as _req

        r = _req.get(link.split("?")[0], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        html = r.text
    except Exception:
        return ""
    chunks: List[str] = []
    for m in re.finditer(r'"value"\s*:\s*"((?:\\.|[^"\\]){80,})"', html):
        val = m.group(1).encode().decode("unicode_escape", errors="replace")
        if len(val) > 80:
            chunks.append(strip_html(val))
    return "\n".join(chunks)[:12_000]


def fetch_comeet(cfg: Dict[str, Any]) -> List[Job]:
    """Fetch from all configured Comeet companies."""
    if not comeet_enabled(cfg):
        return []
    companies = _comeet_block(cfg).get("companies") or []
    if not isinstance(companies, list):
        return []
    out: List[Job] = []
    seen: set[str] = set()
    for entry in companies:
        if not isinstance(entry, dict):
            continue
        for job in fetch_comeet_company(entry, cfg):
            if job.link not in seen:
                seen.add(job.link)
                out.append(job)
    return out
