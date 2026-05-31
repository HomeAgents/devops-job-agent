#!/usr/bin/env bash
# Single orchestrator daily batch (fetch + email). Called by cron or daily_two_slot catch-up.
set -euo pipefail
export TZ="${TZ:-Asia/Jerusalem}"
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
SLOT="${JOB_AGENT_SLOT:-cron}"
LOG="${HOME}/logs/orchestrator-daily-$(date +%Y%m%d)-${SLOT}.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
echo "[$(date '+%H:%M:%S')] daily start slot=${SLOT}" | tee -a "$LOG"
python3 run_orchestrator.py daily >>"$LOG" 2>&1
rc=$?
echo "[$(date '+%H:%M:%S')] daily done exit=${rc} slot=${SLOT}" | tee -a "$LOG"
exit "$rc"
