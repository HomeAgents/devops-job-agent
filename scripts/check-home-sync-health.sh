#!/usr/bin/env bash
# On VM before daily digest: warn if any user's home LinkedIn sync is missing/stale.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a
PYTHONPATH=. python3 <<'PY'
import os
from orchestrator.user_db import UserDB
from orchestrator.job_runner import build_user_config, data_root, project_root
from job_agent.linkedin_home_sync import (
    disable_vm_linkedin_browser,
    home_sync_enabled,
    home_sync_is_fresh,
    load_home_sync_jobs_stale_fallback,
    maybe_alert_missing_home_sync,
)

db = UserDB(os.getenv("ORCHESTRATOR_DB", str(data_root() / "orchestrator.db")))
base = project_root() / "config.json"
for user in db.get_all_users():
    if user.state not in ("scheduled", "ready", "returning", "report_sent"):
        continue
    cfg_path = build_user_config(user, base)
    import json
    from pathlib import Path

    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    if not home_sync_enabled(cfg) or not disable_vm_linkedin_browser(cfg):
        continue
    fresh = home_sync_is_fresh(cfg)
    stale, _ = load_home_sync_jobs_stale_fallback(cfg)
    if fresh:
        print(f"OK {user.email}: home sync fresh")
    elif stale:
        print(f"WARN {user.email}: home sync stale fallback only")
    else:
        print(f"FAIL {user.email}: no home sync — Mac worker required")
        maybe_alert_missing_home_sync(cfg, "pre-daily health check")
PY
