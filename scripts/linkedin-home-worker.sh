#!/usr/bin/env bash
# Run on a home Mac/PC (residential IP): scrape LinkedIn and upload jobs.json to the VM.
#
# Per user: optional ~/.job-agent/home-users/<safe>/browser (login once per user).
# Optional env file: .env.home.<safe> or .env with LINKEDIN_EMAIL matching USER_EMAIL.
#
# Usage:
#   VM_HOST=20.217.203.43 USER_EMAIL=amnon.meron@gmail.com ./scripts/linkedin-home-worker.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_HOST="${VM_HOST:-20.217.203.43}"
VM_USER="${VM_USER:-azureuser}"
USER_EMAIL="${USER_EMAIL:-arkadiy.kats@gmail.com}"
LOCAL_OUT="${LOCAL_OUT:-/tmp/linkedin-home-jobs.json}"
LOG="${HOME}/logs/linkedin-home-worker.log"
mkdir -p "$(dirname "$LOG")"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate

SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
REMOTE_DIR="orchestrator-data/users/${SAFE}/linkedin_home"
REMOTE_FILE="${REMOTE_DIR}/jobs.json"
LOCAL_CFG="/tmp/job-agent-home-${SAFE}.json"
LOCAL_BROWSER="${HOME}/.job-agent/home-users/${SAFE}/browser"
mkdir -p "${LOCAL_BROWSER}"

if [ -f ".env.home.${SAFE}" ]; then
  set -a && . ".env.home.${SAFE}" && set +a
elif [ -f ".env" ]; then
  set -a && . .env && set +a
fi

_run_export() {
  python3 run.py --linkedin-home-export --linkedin-home-export-path "$LOCAL_OUT"
}

echo "[$(date -Iseconds)] home worker start (${USER_EMAIL})" | tee -a "$LOG"

# Ensure per-user config exists on VM, then pull it (keywords/location per user).
ssh -o ConnectTimeout=20 "${VM_USER}@${VM_HOST}" "cd ~/apps/devops-job-agent && . .venv/bin/activate && PYTHONPATH=. python3 -c \"
from pathlib import Path
from orchestrator.user_db import UserDB
from orchestrator.job_runner import build_user_config, project_root, data_root
import os
db = UserDB(os.getenv('ORCHESTRATOR_DB', str(data_root() / 'orchestrator.db')))
u = db.get_or_create('${USER_EMAIL}')
build_user_config(u, project_root() / 'config.json')
\"" 2>>"$LOG" || true

if ! scp -o ConnectTimeout=20 "${VM_USER}@${VM_HOST}:~/${REMOTE_DIR%/linkedin_home}/config.json" "${LOCAL_CFG}" 2>>"$LOG"; then
  echo "[$(date -Iseconds)] WARN: no VM config yet, using local config.json" | tee -a "$LOG"
  LOCAL_CFG="${ROOT}/config.json"
fi

export JOB_AGENT_CONFIG="${LOCAL_CFG}"
PYTHONPATH=. python3 -c "
import json, sys
from pathlib import Path
p = Path('${LOCAL_CFG}')
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg.setdefault('browser', {})['user_data_dir'] = '${LOCAL_BROWSER}'
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
" 2>>"$LOG"

# Keep system awake during scrape (display may still sleep / screen saver).
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -ims -t 2400 -- python3 run.py --linkedin-home-export --linkedin-home-export-path "$LOCAL_OUT" >>"$LOG" 2>&1
else
  python3 run.py --linkedin-home-export --linkedin-home-export-path "$LOCAL_OUT" >>"$LOG" 2>&1
fi
RC=$?
COUNT="$(python3 -c "import json; d=json.load(open('${LOCAL_OUT}')); print(int(d.get('count') or 0))" 2>/dev/null || echo 0)"
if [ "$COUNT" -le 0 ]; then
  echo "[$(date -Iseconds)] export produced 0 jobs (${USER_EMAIL}) — keeping previous VM file" | tee -a "$LOG"
  exit 1
fi

ssh -o ConnectTimeout=20 "${VM_USER}@${VM_HOST}" "mkdir -p ~/${REMOTE_DIR}"
scp -o ConnectTimeout=20 "$LOCAL_OUT" "${VM_USER}@${VM_HOST}:~/${REMOTE_FILE}"
echo "[$(date -Iseconds)] uploaded ${USER_EMAIL} -> ~/${REMOTE_FILE}" | tee -a "$LOG"
