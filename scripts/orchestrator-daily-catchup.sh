#!/usr/bin/env bash
# LaunchAgent tick: run missed morning (09:00) / afternoon (15:00) digests after sleep (ScoutSignal-style).
set -euo pipefail
export TZ="${TZ:-Asia/Jerusalem}"
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
STATE_DIR="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
STATE_FILE="${ORCHESTRATOR_DAILY_STATE_FILE:-${STATE_DIR}/.daily-two-slot-state.json}"
LOG_DIR="${HOME}/logs"
mkdir -p "$LOG_DIR" "$STATE_DIR"
PYTHON="${ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi
TWO_SLOT="${ROOT}/extras/daily_two_slot.py"
if [ ! -f "$TWO_SLOT" ]; then
  TWO_SLOT="${HOME}/scripts/daily_two_slot.py"
fi
exec "$PYTHON" "$TWO_SLOT" \
  --state-file "$STATE_FILE" \
  --morning-start-hour 9 \
  --morning-start-minute 0 \
  --afternoon-start-hour 15 \
  --afternoon-start-minute 0 \
  --log-file "${LOG_DIR}/orchestrator-daily-two-slot.log" \
  -- \
  /bin/bash "${ROOT}/scripts/run-daily-jobs-once.sh"
