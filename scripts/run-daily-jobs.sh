#!/usr/bin/env bash
# Master daily trigger (09:00 Asia/Jerusalem). Per-user days live in orchestrator DB.
set -euo pipefail
export TZ=Asia/Jerusalem
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/orchestrator-daily-$(date +%Y%m%d).log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a
[ -f orchestrator.env ] && set -a && . orchestrator.env && set +a
echo "[$(date '+%H:%M:%S')] daily start" | tee -a "$LOG"
python3 run_orchestrator.py daily >>"$LOG" 2>&1
echo "[$(date '+%H:%M:%S')] daily done" | tee -a "$LOG"
