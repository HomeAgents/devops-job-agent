#!/usr/bin/env bash
# Ensure digest Remove/Status HTTP server is up (orchestrator / VM).
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/digest-remove-server.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
export ORCHESTRATOR_DATA_DIR="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
if .venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from orchestrator.digest_server import ensure_shared_remove_server
sys.exit(0 if ensure_shared_remove_server() else 1)
" >>"$LOG" 2>&1; then
  echo "[$(date -Iseconds)] digest-remove-server OK" >>"$LOG"
else
  echo "[$(date -Iseconds)] digest-remove-server FAILED — starting via script" >>"$LOG"
  if ! pgrep -f "run.py --digest-remove-server" >/dev/null 2>&1; then
    nohup bash "${ROOT}/scripts/digest-remove-server.sh" >>"$LOG" 2>&1 &
    sleep 3
  fi
fi
