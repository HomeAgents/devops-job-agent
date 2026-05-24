#!/usr/bin/env bash
# Poll genie4cv@gmail.com inbox; start VM activity; auto-stop after idle window.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/orchestrator-poll.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "[poll-inbox] Missing ${PYTHON} — run: python3 -m venv .venv && pip install -r requirements.txt" >>"$LOG"
  exit 1
fi
[ -f .env ] && set -a && . .env && set +a
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
if command -v az >/dev/null 2>&1; then
  az login --identity --allow-no-subscriptions >/dev/null 2>&1 || true
fi
export ORCHESTRATOR_ACTIVITY_FILE="${ORCHESTRATOR_ACTIVITY_FILE:-${HOME}/orchestrator-data/last_activity}"
"$PYTHON" run_orchestrator.py poll-inbox --idle-minutes "${ORCHESTRATOR_IDLE_MINUTES:-15}" >>"$LOG" 2>&1
