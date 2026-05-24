#!/usr/bin/env bash
# Log in to LinkedIn on the VM (requires VNC: ssh -L 5901:127.0.0.1:5901 azureuser@VM && open vnc://127.0.0.1:5901)
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
USER_EMAIL="${1:-arkadiy.kats@gmail.com}"
LOG="${HOME}/logs/linkedin-login.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
export DISPLAY="${DISPLAY:-:1}"
SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
export JOB_AGENT_CONFIG="${HOME}/orchestrator-data/users/${SAFE}/config.json"
export ORCHESTRATOR_ACTIVITY_FILE="${ORCHESTRATOR_ACTIVITY_FILE:-${HOME}/orchestrator-data/last_activity}"
echo "[$(date -Iseconds)] LinkedIn login start (DISPLAY=$DISPLAY)" | tee -a "$LOG"
PYTHONPATH=. python3 run.py --config "$JOB_AGENT_CONFIG" --linkedin-login --linkedin-login-wait 45 2>&1 | tee -a "$LOG"
