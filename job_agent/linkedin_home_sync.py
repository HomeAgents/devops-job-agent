"""Import LinkedIn jobs scraped on a home machine (residential IP) into VM runs."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from job_agent.models import Job


def _home_sync_block(cfg: Dict[str, Any]) -> Dict[str, Any]:
    li = cfg.get("linkedin") if isinstance(cfg.get("linkedin"), dict) else {}
    block = li.get("home_sync")
    return block if isinstance(block, dict) else {}


def home_sync_enabled(cfg: Dict[str, Any]) -> bool:
    block = _home_sync_block(cfg)
    if "enabled" in block:
        return bool(block.get("enabled"))
    return os.getenv("LINKEDIN_HOME_SYNC", "").strip().lower() in ("1", "true", "yes")


def home_sync_path(cfg: Dict[str, Any]) -> Path:
    block = _home_sync_block(cfg)
    explicit = (block.get("import_path") or os.getenv("LINKEDIN_HOME_SYNC_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    user_email = str(cfg.get("_user_email") or "").strip().lower()
    if user_email:
        from orchestrator.user_db import sanitize_email

        data = Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))
        return data / "users" / sanitize_email(user_email) / "linkedin_home" / "jobs.json"
    return Path.home() / ".job-agent" / "linkedin_home" / "jobs.json"


def home_sync_max_age_hours(cfg: Dict[str, Any]) -> float:
    block = _home_sync_block(cfg)
    raw = block.get("max_age_hours") or os.getenv("LINKEDIN_HOME_SYNC_MAX_AGE_HOURS", 18)
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 18.0


def disable_vm_linkedin_browser(cfg: Dict[str, Any]) -> bool:
    """When True, never run LinkedIn Playwright on the VM (use home sync only)."""
    block = _home_sync_block(cfg)
    if "disable_vm_linkedin_browser" in block:
        return bool(block.get("disable_vm_linkedin_browser"))
    return home_sync_enabled(cfg)


def stale_fallback_hours(cfg: Dict[str, Any]) -> float:
    block = _home_sync_block(cfg)
    raw = block.get("stale_fallback_hours") or os.getenv("LINKEDIN_HOME_STALE_FALLBACK_HOURS", 36)
    try:
        return max(float(home_sync_max_age_hours(cfg)), float(raw))
    except (TypeError, ValueError):
        return 36.0


def skip_vm_linkedin_when_fresh(cfg: Dict[str, Any]) -> bool:
    block = _home_sync_block(cfg)
    if "skip_vm_linkedin_when_fresh" in block:
        return bool(block.get("skip_vm_linkedin_when_fresh"))
    return True


def skip_vm_reach_out_when_fresh(cfg: Dict[str, Any]) -> bool:
    block = _home_sync_block(cfg)
    if "skip_vm_reach_out_when_fresh" in block:
        return bool(block.get("skip_vm_reach_out_when_fresh"))
    return True


def skip_google_browser_when_fresh(cfg: Dict[str, Any]) -> bool:
    block = _home_sync_block(cfg)
    if "skip_google_browser_when_fresh" in block:
        return bool(block.get("skip_google_browser_when_fresh"))
    return True


def home_sync_is_fresh(cfg: Dict[str, Any]) -> bool:
    """True when home_sync is enabled and the import file exists and is within max_age."""
    if not home_sync_enabled(cfg):
        return False
    path = home_sync_path(cfg)
    if not path.is_file():
        return False
    try:
        age_h = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
    except OSError:
        return False
    return age_h <= home_sync_max_age_hours(cfg)


def apply_fast_vm_overrides_when_home_sync_fresh(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Disable slow VM browser work when home Mac already synced LinkedIn jobs."""
    if os.getenv("LINKEDIN_HOME_EXPORT", "").strip().lower() in ("1", "true", "yes"):
        return cfg
    if not home_sync_is_fresh(cfg):
        return cfg
    li = cfg.get("linkedin")
    if not isinstance(li, dict):
        return cfg
    js = li.get("jobs_search")
    if not isinstance(js, dict):
        js = {}
        li = {**li, "jobs_search": js}
    out = {**cfg, "linkedin": {**li}}
    li_out = out["linkedin"]
    js_out = dict(li_out.get("jobs_search") or js)
    if skip_vm_reach_out_when_fresh(cfg):
        js_out["scrape_reach_out_people"] = False
    li_out = {**li_out, "jobs_search": js_out}
    out["linkedin"] = li_out
    if skip_vm_reach_out_when_fresh(cfg):
        print(
            "LinkedIn reach-out on VM: skipped (fresh home sync present)",
            file=sys.stderr,
        )
    if skip_google_browser_when_fresh(cfg):
        gw = out.get("google_web_browser")
        if isinstance(gw, dict):
            out = {**out, "google_web_browser": {**gw, "enabled": False}}
            print(
                "Google browser on VM: skipped (fresh home sync present)",
                file=sys.stderr,
            )
    return out


def job_to_dict(job: Job) -> Dict[str, Any]:
    return {
        "source": job.source,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "link": job.link,
        "posted": job.posted,
        "score": job.score,
        "search_fallback": job.search_fallback,
        "raw": job.raw if isinstance(job.raw, dict) else {},
    }


def job_from_dict(data: Dict[str, Any]) -> Job:
    raw = data.get("raw")
    return Job(
        source=str(data.get("source") or "linkedin_home_sync"),
        company=str(data.get("company") or "Unknown"),
        title=str(data.get("title") or ""),
        location=str(data.get("location") or ""),
        link=str(data.get("link") or ""),
        posted=str(data.get("posted") or "recent"),
        score=int(data.get("score") or 0),
        search_fallback=str(data.get("search_fallback") or ""),
        raw=raw if isinstance(raw, dict) else {},
    )


def export_linkedin_jobs(path: Path, jobs: List[Job], *, meta: Optional[Dict[str, Any]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(jobs),
        "meta": meta or {},
        "jobs": [job_to_dict(j) for j in jobs],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"LinkedIn home sync: wrote {len(jobs)} job(s) to {path}", file=sys.stderr)


def _load_home_sync_file(
    cfg: Dict[str, Any],
    *,
    max_age_hours: float,
    stale_label: str = "",
) -> Tuple[List[Job], str]:
    path = home_sync_path(cfg)
    if not path.is_file():
        return [], "home sync file missing — run linkedin-home-worker.sh on your Mac"
    try:
        age_h = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
    except OSError:
        return [], "home sync file unreadable"
    if age_h > max_age_hours:
        return [], f"home sync too old ({age_h:.1f}h, max {max_age_hours:.0f}h)"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"home sync unreadable: {exc}"
    rows = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], "home sync invalid format"
    jobs = [job_from_dict(r) for r in rows if isinstance(r, dict) and r.get("link")]
    for job in jobs:
        raw = job.raw if isinstance(job.raw, dict) else {}
        job.raw = {**raw, "_home_sync": True}
    exported = payload.get("exported_at") if isinstance(payload, dict) else ""
    msg = f"home sync {len(jobs)} job(s) from {path.name}"
    if stale_label:
        msg += f" ({stale_label})"
    elif exported:
        msg += f" (exported {exported})"
    return jobs, msg


def load_home_sync_jobs(cfg: Dict[str, Any]) -> Tuple[List[Job], str]:
    """Load jobs if sync file exists and is fresh enough. Returns (jobs, status_message)."""
    if not home_sync_enabled(cfg):
        return [], ""
    return _load_home_sync_file(cfg, max_age_hours=home_sync_max_age_hours(cfg))


def load_home_sync_jobs_stale_fallback(cfg: Dict[str, Any]) -> Tuple[List[Job], str]:
    """Use last home export when fresh file expired (better than zero LinkedIn jobs)."""
    if not home_sync_enabled(cfg):
        return [], ""
    return _load_home_sync_file(
        cfg,
        max_age_hours=stale_fallback_hours(cfg),
        stale_label="stale fallback",
    )


def resolve_linkedin_home_sync(cfg: Dict[str, Any]) -> Tuple[List[Job], str, bool]:
    """
    Pick home-sync jobs (fresh, else stale fallback).
    Returns (jobs, message, skip_vm_linkedin_browser).
    """
    if not home_sync_enabled(cfg):
        return [], "", False

    jobs, msg = load_home_sync_jobs(cfg)
    stale_msg = ""
    if not jobs:
        stale_jobs, stale_msg = load_home_sync_jobs_stale_fallback(cfg)
        if stale_jobs:
            jobs, msg = stale_jobs, stale_msg
        else:
            detail = msg or stale_msg or "missing"
            print(f"LinkedIn home sync: {detail}", file=sys.stderr)

    skip_vm = disable_vm_linkedin_browser(cfg)
    if skip_vm:
        if jobs:
            print(
                "LinkedIn VM browser: disabled (home sync is the only LinkedIn source)",
                file=sys.stderr,
            )
        else:
            print(
                "LinkedIn VM browser: disabled — no home sync file; "
                "run ./scripts/linkedin-home-worker.sh on Mac (see docs/LINKEDIN_HOME_WORKER.md)",
                file=sys.stderr,
            )
            maybe_alert_missing_home_sync(cfg, msg or stale_msg or "missing")
    elif jobs and skip_vm_linkedin_when_fresh(cfg):
        skip_vm = True
        print("LinkedIn browser on VM: skipped (fresh home sync present)", file=sys.stderr)

    return jobs, msg, skip_vm


def _home_sync_missing_alert_path(cfg: Dict[str, Any]) -> Path:
    """One admin alert per day; shared LinkedIn uses a global marker, not per-subscriber."""
    try:
        from orchestrator.linkedin_shared_session import shared_home_linkedin_enabled
    except ImportError:
        shared_home_linkedin_enabled = lambda: False  # type: ignore

    if shared_home_linkedin_enabled():
        return Path.home() / ".job-agent" / ".home-sync-missing-alert-sent"
    return home_sync_path(cfg).parent / ".home-sync-alert-sent"


def maybe_alert_missing_home_sync(cfg: Dict[str, Any], detail: str) -> None:
    """Email admin once per day when home sync is required but missing (never subscribers)."""
    if not home_sync_enabled(cfg) or not disable_vm_linkedin_browser(cfg):
        return
    block = _home_sync_block(cfg)
    if block.get("alert_on_missing", True) is False:
        return
    from orchestrator.linkedin_alerts import orchestrator_notify_email

    if not orchestrator_notify_email():
        return
    user = str(cfg.get("_user_email") or "user").strip()
    path = _home_sync_missing_alert_path(cfg)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if path.is_file() and path.read_text(encoding="utf-8").strip() == today:
            return
    except OSError:
        pass
    try:
        from orchestrator.linkedin_shared_session import (
            linkedin_session_owner_email,
            shared_home_linkedin_enabled,
        )
    except ImportError:
        shared_home_linkedin_enabled = lambda: False  # type: ignore
        linkedin_session_owner_email = lambda: ""  # type: ignore

    if shared_home_linkedin_enabled():
        owner = linkedin_session_owner_email() or "session owner"
        reason = (
            f"Shared LinkedIn home sync missing or stale (noticed during digest for {user}). "
            f"VM LinkedIn is off (datacenter IP blocked). "
            f"Cron will retry; digests use Greenhouse/ATS until sync succeeds. "
            f"Admin: run linkedin-bootstrap + linkedin-home-sync on home Mac for {owner}. ({detail})"
        )
    else:
        reason = (
            f"Home LinkedIn sync missing for {user}. "
            f"VM LinkedIn is off (datacenter IP blocked). "
            f"Worker Mac will retry on cron; digests use Greenhouse/ATS until sync succeeds. "
            f"Admin: bootstrap session for this user once. ({detail})"
        )
    from job_agent.browser.session import send_linkedin_alert_once

    send_linkedin_alert_once(cfg, reason=reason)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(today, encoding="utf-8")
    except OSError:
        pass


def fetch_and_export_linkedin_for_home(cfg: Dict[str, Any], out_path: Path) -> int:
    """Run LinkedIn browser fetches locally and write sync JSON."""
    from job_agent.sources.linkedin_browser import (
        build_linkedin_jobs_search_url,
        fetch_linkedin_jobs,
    )
    from job_agent.sources.linkedin_posts_browser import fetch_linkedin_posts

    os.environ["LINKEDIN_HOME_EXPORT"] = "1"
    from job_agent.sources.linkedin_browser import jobs_search_queries

    queries = jobs_search_queries(cfg)
    search_url = build_linkedin_jobs_search_url(cfg)
    search_urls = [
        build_linkedin_jobs_search_url(cfg, keywords=q) for q in queries
    ] if len(queries) > 1 else [search_url]
    jobs: List[Job] = []
    try:
        jobs.extend(fetch_linkedin_jobs(cfg))
        include_posts = os.getenv("LINKEDIN_HOME_INCLUDE_POSTS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if include_posts:
            jobs.extend(fetch_linkedin_posts(cfg))
        for job in jobs:
            raw = job.raw if isinstance(job.raw, dict) else {}
            job.raw = {**raw, "_home_sync": True, "search_url": search_url}
        meta_export: Dict[str, Any] = {
            "host": os.uname().nodename if hasattr(os, "uname") else "home",
            "search_url": search_url,
            "search_urls": search_urls,
            "search_queries": queries,
            "multi_search": len(queries) > 1,
            "subscriber_email": str(cfg.get("_user_email") or "").strip().lower(),
        }
        try:
            from orchestrator.linkedin_shared_session import (
                linkedin_session_owner_email,
                shared_home_linkedin_enabled,
            )

            if shared_home_linkedin_enabled():
                meta_export["linkedin_shared_session"] = True
                meta_export["linkedin_session_owner"] = linkedin_session_owner_email()
        except ImportError:
            pass
        export_linkedin_jobs(out_path, jobs, meta=meta_export)
        return 0 if jobs else 1
    finally:
        os.environ.pop("LINKEDIN_HOME_EXPORT", None)
