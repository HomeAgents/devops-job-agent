#!/usr/bin/env bash
# Persistent digest Remove/Status server (multi-user: resolves profile from token or job link).
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
USER_EMAIL="${1:-${ORCHESTRATOR_ADMIN_EMAIL:-arkadiy.kats@gmail.com}}"
LOG="${HOME}/logs/digest-remove-server.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
export ORCHESTRATOR_DATA_DIR="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
export JOB_AGENT_CONFIG="${ORCHESTRATOR_DATA_DIR}/users/${SAFE}/config.json"
if [ ! -f "$JOB_AGENT_CONFIG" ]; then
  echo "Missing config: $JOB_AGENT_CONFIG" >&2
  exit 1
fi
exec >>"$LOG" 2>&1
echo "[$(date -Iseconds)] digest-remove-server start JOB_AGENT_CONFIG=$JOB_AGENT_CONFIG"
PYTHONPATH=. python3 run.py --digest-remove-server
