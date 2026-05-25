from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_agent.query_build import (
    build_unified_site_query_templates,
    or_terms_from_role_keywords,
    role_or_block,
)
from orchestrator.keyword_review import normalize_linkedin_keywords
from orchestrator.user_db import UserDB, UserRecord, sanitize_email


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data")))


def user_work_dir(user: UserRecord) -> Path:
    d = data_root() / "users" / sanitize_email(user.email)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _google_after_clause(ats: dict[str, Any]) -> str:
    from datetime import date, timedelta

    if ats.get("omit_after_clause"):
        return ""
    after_days = int(ats.get("after_days_ago") or 40)
    return f" after:{(date.today() - timedelta(days=after_days)).isoformat()}"


def _sync_google_search_from_linkedin(cfg: dict[str, Any], keywords: str, location: str) -> None:
    """One role OR-block + location for all Google web / ATS site: queries."""
    ats = cfg.get("ats_google_site_search")
    if not isinstance(ats, dict) or not ats.get("enabled") or not keywords:
        return
    ats = cfg.setdefault("ats_google_site_search", {})
    role_block = role_or_block(keywords)
    after = _google_after_clause(ats)
    loc = location or "Israel"
    ats["role_phrases"] = [role_block]
    ats["extra_query_templates"] = [
        t.replace("{after}", after) for t in build_unified_site_query_templates(role_block, loc, "{after}")
    ]
    # User-approved filter only — do not merge global DevOps OR blocks on top.
    ats["prepend_builtin_devops_or_blocks"] = False
    ats["merge_roles_from_serpapi_template"] = False
    ats["combine_role_phrases_or"] = True

    terms = or_terms_from_role_keywords(keywords)
    if terms:
        sc = cfg.setdefault("scoring", {})
        if isinstance(sc, dict):
            existing = [str(k) for k in (sc.get("keywords") or [])]
            seen = {k.lower() for k in existing}
            for t in terms:
                if t.lower() not in seen:
                    existing.append(t)
                    seen.add(t.lower())
            sc["keywords"] = existing


def build_user_config(user: UserRecord, base_config_path: Path) -> Path:
    work = user_work_dir(user)
    cfg = json.loads(base_config_path.read_text(encoding="utf-8"))
    cfg = deepcopy(cfg)

    keywords_raw = (user.meta.get("approved_keyword_query") or user.keywords or "").strip()
    location = (
        str(user.meta.get("location_hint") or "").strip()
        or str(cfg.get("location_hint") or "").strip()
        or "Israel"
    )
    keywords = normalize_linkedin_keywords(keywords_raw, location=location)
    js = cfg.setdefault("linkedin", {}).setdefault("jobs_search", {})
    js["keywords"] = keywords
    js["location"] = location
    if not js.get("f_TPR"):
        js["f_TPR"] = "r2592000"  # past month; user can override in base config
    cfg["location_hint"] = location

    _sync_google_search_from_linkedin(cfg, keywords, location)

    cfg["digest_min_minutes_between_sends"] = 0

    cv_path = user.cv_path
    if cv_path and Path(cv_path).exists():
        cv_fit = cfg.setdefault("cv_fit", {})
        cv_fit["enabled"] = True
        cv_fit["profile_path"] = str(Path(cv_path).resolve())

    browser = cfg.setdefault("browser", {})
    browser["user_data_dir"] = str((work / "browser").resolve())

    digest_remove = cfg.setdefault("digest_remove", {})
    digest_remove["ignore_store_path"] = str((work / "digest_ignore_links.json").resolve())
    secret = os.getenv("ORCHESTRATOR_REMOVE_SECRET", "").strip()
    if secret:
        digest_remove["secret"] = secret
    base_url = os.getenv("ORCHESTRATOR_REMOVE_BASE_URL", "").strip()
    if base_url:
        digest_remove["base_url"] = base_url.rstrip("/")
        digest_remove["host"] = "0.0.0.0"
    elif os.getenv("ORCHESTRATOR_REMOVE_PUBLIC", "").strip().lower() in ("1", "true", "yes"):
        digest_remove["host"] = "0.0.0.0"

    cfg["_project_root"] = str(work.resolve())
    cfg["_jobs_db"] = str((work / "jobs.db").resolve())
    cfg["_user_email"] = user.email.strip().lower()

    jt = cfg.setdefault("job_tracker", {})
    if isinstance(jt, dict):
        jt["path"] = str((work / "job_tracker.xlsx").resolve())

    out = work / "config.json"
    out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _digest_was_sent(log_text: str) -> bool:
    if "Sent digest email" in log_text:
        return True
    if "Skipping digest send" in log_text:
        return False
    return False


def _finish_job_run(user: UserRecord, db: UserDB, proc: subprocess.CompletedProcess, log_text: str) -> int:
    if proc.returncode != 0:
        db.update_user(user.id, state="returning")
        return proc.returncode

    digest_sent = _digest_was_sent(log_text)
    meta = dict(user.meta)
    updates: dict = {"meta": meta, "pending_feedback": False}

    if digest_sent:
        meta["first_execution_complete"] = True
        updates["state"] = "report_sent"
        updates["report_sent_at"] = _utc_now()
        # Feedback only after first real digest; enable when ORCHESTRATOR_FEEDBACK_ENABLED=1
        if os.getenv("ORCHESTRATOR_FEEDBACK_ENABLED", "0").strip().lower() in ("1", "true", "yes"):
            updates["pending_feedback"] = True
            updates["feedback_sent_at"] = None
    else:
        updates["state"] = "returning"

    db.update_user(user.id, **updates)
    return proc.returncode


def run_job_for_user(user: UserRecord, db: UserDB, *, dry_run: bool = False) -> int:
    root = project_root()
    base = Path(os.getenv("ORCHESTRATOR_BASE_CONFIG", str(root / "config.json")))
    if not base.exists():
        base = root / "config.browser.example.json"
    config_path = build_user_config(user, base)
    work = user_work_dir(user)
    db_path = work / "jobs.db"

    env = os.environ.copy()
    env["JOB_AGENT_CONFIG"] = str(config_path)
    env["EMAIL_TO"] = user.email
    env["GENIE4CV_SETTINGS"] = env.get("GENIE4CV_SETTINGS", str(Path.home() / "genie4cv" / "local.settings.json"))

    cmd = [sys.executable, str(root / "run.py"), "--config", str(config_path), "--db", str(db_path)]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--email-all-fetched")

    timeout = int(os.getenv("ORCHESTRATOR_JOB_TIMEOUT", "1800"))
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"Job for {user.email} timed out after {timeout}s", file=sys.stderr)
        (work / "last-run.log").write_text(f"TIMEOUT after {timeout}s\n", encoding="utf-8")
        db.update_user(user.id, state="returning")
        return 1
    combined = proc.stdout + "\n" + proc.stderr
    (work / "last-run.log").write_text(combined, encoding="utf-8")

    if dry_run:
        return proc.returncode
    return _finish_job_run(user, db, proc, combined)


def run_docker_job(user: UserRecord, db: UserDB) -> int:
    """Run isolated job in Docker if ORCHESTRATOR_USE_DOCKER=1."""
    if os.getenv("ORCHESTRATOR_USE_DOCKER", "").strip().lower() not in ("1", "true", "yes"):
        return run_job_for_user(user, db)

    work = user_work_dir(user)
    build_user_config(user, Path(os.getenv("ORCHESTRATOR_BASE_CONFIG", str(project_root() / "config.json"))))
    image = os.getenv("ORCHESTRATOR_DOCKER_IMAGE", "job-agent:latest")

    cmd = [
        "docker",
        "run",
        "--rm",
        "--memory=2g",
        "--cpus=1",
        "-v",
        f"{work}:/work",
        "-v",
        f"{Path.home() / 'genie4cv'}:/genie4cv:ro",
        "-e",
        f"EMAIL_TO={user.email}",
        "-e",
        "GENIE4CV_SETTINGS=/genie4cv/local.settings.json",
        "-e",
        "JOB_AGENT_CONFIG=/work/config.json",
        image,
        "--config",
        "/work/config.json",
        "--db",
        "/work/jobs.db",
        "--email-all-fetched",
    ]
    timeout = int(os.getenv("ORCHESTRATOR_JOB_TIMEOUT", "1800"))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"Docker job for {user.email} timed out after {timeout}s", file=sys.stderr)
        (work / "last-docker.log").write_text(f"TIMEOUT after {timeout}s\n", encoding="utf-8")
        db.update_user(user.id, state="returning")
        return 1
    combined = proc.stdout + proc.stderr
    (work / "last-docker.log").write_text(combined, encoding="utf-8")
    return _finish_job_run(user, db, proc, combined)
