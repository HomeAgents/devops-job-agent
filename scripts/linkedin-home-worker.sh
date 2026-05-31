#!/usr/bin/env bash
# Home Mac worker: LinkedIn job search for one orchestrator user (keywords from their config).
# Default: one shared LinkedIn login (ORCHESTRATOR_LINKEDIN_OWNER_EMAIL) for all users — search only.
# Called by linkedin-home-workers-all.sh — subscribers never run this.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_HOST="${VM_HOST:-}"
VM_USER="${VM_USER:-azureuser}"
USER_EMAIL="${USER_EMAIL:-arkadiy.kats@gmail.com}"
LOCAL_OUT="${LOCAL_OUT:-/tmp/linkedin-home-jobs.json}"
LOG="${HOME}/logs/linkedin-home-worker.log"
ORCHESTRATOR_DATA="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
mkdir -p "$(dirname "$LOG")"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate

SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
REMOTE_DIR="orchestrator-data/users/${SAFE}/linkedin_home"
REMOTE_FILE="${REMOTE_DIR}/jobs.json"
LOCAL_SYNC_DIR="${ORCHESTRATOR_DATA}/users/${SAFE}/linkedin_home"
LOCAL_SYNC_FILE="${LOCAL_SYNC_DIR}/jobs.json"
LOCAL_USER_CFG="${LOCAL_SYNC_DIR%/linkedin_home}/config.json"
LOCAL_CFG="/tmp/job-agent-home-${SAFE}.json"
mkdir -p "${LOCAL_SYNC_DIR}"

LOCAL_BROWSER="$(PYTHONPATH=. python3 -c "
from orchestrator.linkedin_credentials import apply_linkedin_env_for_user, user_record_for_email
from orchestrator.linkedin_shared_session import (
    home_browser_profile_dir,
    linkedin_session_owner_email,
    shared_home_linkedin_enabled,
)
from orchestrator.user_db import UserDB
import os
email = os.environ['USER_EMAIL'].strip().lower()
db = UserDB(os.getenv('ORCHESTRATOR_DB', '${ORCHESTRATOR_DATA}/orchestrator.db'))
u = user_record_for_email(db, email)
owner = linkedin_session_owner_email() if shared_home_linkedin_enabled() else email
if not owner:
    owner = email
ou = user_record_for_email(db, owner) if owner != email else u
apply_linkedin_env_for_user(owner, meta=(ou.meta if ou else (u.meta if u else {})))
print(home_browser_profile_dir(email))
" 2>>"$LOG")"
mkdir -p "${LOCAL_BROWSER}"

# Mac / local orchestrator: use per-user config; skip dead Azure VM SSH unless VM_HOST is set.
VM_ONLINE=0
if [ -n "${VM_HOST}" ] && [ "${ORCHESTRATOR_SKIP_VM:-0}" != "1" ]; then
  if ssh -o ConnectTimeout=8 "${VM_USER}@${VM_HOST}" "true" 2>>"$LOG"; then
    VM_ONLINE=1
  fi
fi

if [ -f "${LOCAL_USER_CFG}" ]; then
  cp "${LOCAL_USER_CFG}" "${LOCAL_CFG}"
  echo "[$(date -Iseconds)] using local orchestrator config ${LOCAL_USER_CFG}" >>"$LOG"
elif [ "$VM_ONLINE" -eq 1 ]; then
  if scp -o ConnectTimeout=15 "${VM_USER}@${VM_HOST}:~/${REMOTE_DIR%/linkedin_home}/config.json" "${LOCAL_CFG}" 2>>"$LOG"; then
    echo "[$(date -Iseconds)] pulled VM config for ${USER_EMAIL}" >>"$LOG"
  else
    echo "[$(date -Iseconds)] WARN: no VM config, using repo config.json" | tee -a "$LOG"
    LOCAL_CFG="${ROOT}/config.json"
  fi
else
  echo "[$(date -Iseconds)] WARN: no local user config, using repo config.json" | tee -a "$LOG"
  LOCAL_CFG="${ROOT}/config.json"
fi

export JOB_AGENT_CONFIG="${LOCAL_CFG}"
PYTHONPATH=. python3 -c "
import json, sys
from pathlib import Path
p = Path('${LOCAL_CFG}')
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg.setdefault('browser', {})['user_data_dir'] = '${LOCAL_BROWSER}'
cfg['_user_email'] = '${USER_EMAIL}'.strip().lower()
js = cfg.setdefault('linkedin', {}).setdefault('jobs_search', {})
js['scrape_reach_out_people'] = False
js['max_jobs_reach_out_scrape'] = 0
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
" 2>>"$LOG"

if [ "${ORCHESTRATOR_LINKEDIN_SHARED_SESSION:-1}" != "0" ]; then
  echo "[$(date -Iseconds)] home worker start (${USER_EMAIL}) shared LinkedIn profile -> ${LOCAL_BROWSER}" | tee -a "$LOG"
else
  echo "[$(date -Iseconds)] home worker start (${USER_EMAIL})" | tee -a "$LOG"
fi

if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -ims -t 2400 -- python3 run.py --linkedin-home-export --linkedin-home-export-path "$LOCAL_OUT" >>"$LOG" 2>&1
else
  python3 run.py --linkedin-home-export --linkedin-home-export-path "$LOCAL_OUT" >>"$LOG" 2>&1
fi
RC=$?
COUNT="$(python3 -c "import json; d=json.load(open('${LOCAL_OUT}')); print(int(d.get('count') or 0))" 2>/dev/null || echo 0)"
if [ "$COUNT" -le 0 ]; then
  echo "[$(date -Iseconds)] export produced 0 jobs (${USER_EMAIL}) — keeping previous sync file" | tee -a "$LOG"
  exit 1
fi

if [ "$VM_ONLINE" -eq 1 ]; then
  ssh -o ConnectTimeout=15 "${VM_USER}@${VM_HOST}" "mkdir -p ~/${REMOTE_DIR}"
  scp -o ConnectTimeout=15 "$LOCAL_OUT" "${VM_USER}@${VM_HOST}:~/${REMOTE_FILE}"
  echo "[$(date -Iseconds)] uploaded ${USER_EMAIL} -> ~/${REMOTE_FILE}" | tee -a "$LOG"
else
  cp "$LOCAL_OUT" "$LOCAL_SYNC_FILE"
  echo "[$(date -Iseconds)] saved ${USER_EMAIL} -> ${LOCAL_SYNC_FILE}" | tee -a "$LOG"
fi
exit "$RC"
