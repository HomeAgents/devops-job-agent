#!/usr/bin/env bash
# Cron entry: run orchestrator daily at 09:xx / 15:xx and mark two-slot state on success.
set -euo pipefail
export TZ="${TZ:-Asia/Jerusalem}"
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
hour=$(date +%H)
if [ "$hour" -lt 15 ]; then
  export JOB_AGENT_SLOT=morning
else
  export JOB_AGENT_SLOT=afternoon
fi
if "${ROOT}/scripts/run-daily-jobs-once.sh"; then
  "${ROOT}/scripts/mark-orchestrator-daily-slot.sh" "$JOB_AGENT_SLOT"
  exit 0
fi
exit 1
