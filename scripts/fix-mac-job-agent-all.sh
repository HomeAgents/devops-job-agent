#!/usr/bin/env bash
# One-shot Mac production fixes: configs, permissions, meta, Amnon new-only, remove URL, launchd.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
DATA="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

echo "== chmod secrets =="
chmod 600 .env 2>/dev/null || true
chmod 600 "${HOME}/.job-agent/.digest-remove-secret" 2>/dev/null || true
find "$DATA/users" -name 'config.json' -exec chmod 600 {} \; 2>/dev/null || true

echo "== DB + user configs =="
export ORCHESTRATOR_DB="${ORCHESTRATOR_DB:-${DATA}/orchestrator.db}"
PYTHONPATH=. python3 <<'PY'
import json
from pathlib import Path

from orchestrator.job_runner import build_user_config, data_root, project_root
from orchestrator.user_db import UserDB

ARKADIY_QUERIES = [
    "senior devops manager",
    "head of devops",
    "devops manager",
    "director of devops",
    "devops director",
    "devops lead",
    "devops tech lead",
    "sre manager",
    "sre devops lead",
    "platform engineering manager",
    "infrastructure manager",
    "head of infrastructure",
    "cloud platform sre",
    "מנהל DevOps",
    "דירקטור DevOps",
]

db = UserDB(str(data_root() / "orchestrator.db"))
base = project_root() / "config.json"

for email in ("arkadiy.kats@gmail.com", "amnon.meron@gmail.com"):
    u = db.get_or_create(email)
    meta = dict(u.meta)
    if email.startswith("arkadiy"):
        kw = " | ".join(ARKADIY_QUERIES)
        db.update_user(u.id, keywords=kw)
        meta["linkedin_search_queries"] = ARKADIY_QUERIES
        meta.pop("approved_keyword_query", None)
        db.update_user(u.id, meta=meta)
        u = db.get_or_create(email)
    else:
        meta.pop("approved_keyword_query", None)
        db.update_user(u.id, meta=meta)
        u = db.get_or_create(email)

    path = build_user_config(u, base, db)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if email.startswith("amnon"):
        cfg["digest_email_only_new"] = True
    dr = cfg.setdefault("digest_remove", {})
    dr["enabled"] = True
    base_url = __import__("os").environ.get("ORCHESTRATOR_REMOVE_BASE_URL", "").strip()
    if base_url:
        dr["base_url"] = base_url.rstrip("/")
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    js = (cfg.get("linkedin") or {}).get("jobs_search") or {}
    print(
        email,
        "only_new=",
        cfg.get("digest_email_only_new"),
        "queries=",
        len(js.get("queries") or []),
        "multi=",
        js.get("multi_search"),
    )
PY

echo "== remove URL sync =="
"${ROOT}/scripts/sync-remove-base-url.sh" || true

echo "== launchd + cron =="
"${ROOT}/scripts/install-mac-job-agent-schedule.sh"
if [ -x "${ROOT}/scripts/install-mac-remove-stack.sh" ]; then
  "${ROOT}/scripts/install-mac-remove-stack.sh" || echo "WARN: remove stack install had issues (tunnel may already run)"
fi

echo "== ensure remove server =="
"${ROOT}/scripts/ensure-digest-remove-server.sh" || true

if [ "${SKIP_LINKEDIN_SYNC:-0}" != "1" ]; then
  echo "== LinkedIn home sync (all users; may take several minutes) =="
  "${ROOT}/scripts/linkedin-home-workers-all.sh" | tail -15
fi

echo "== health check =="
"${ROOT}/scripts/check-orchestrator-health.sh" || true

echo "== pytest (quick) =="
"${ROOT}/.venv/bin/python3" -m pytest tests/test_orchestrator.py tests/test_linkedin_multi_search.py tests/test_linkedin_alerts.py -q

echo "== fix-mac-job-agent-all DONE =="
