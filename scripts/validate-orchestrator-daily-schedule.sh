#!/usr/bin/env bash
# Validate Job Agent two-slot schedule (cron + LaunchAgent + dry-run planner).
set -euo pipefail
export TZ=Asia/Jerusalem
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
STATE_FILE="${ORCHESTRATOR_DAILY_STATE_FILE:-${HOME}/orchestrator-data/.daily-two-slot-state.json}"
LABEL="com.devops-job-agent.daily-two-slot"
ERR=0

warn() { echo "WARN: $*" >&2; ERR=1; }
ok() { echo "OK: $*"; }

if ! crontab -l 2>/dev/null | grep -q 'run-daily-jobs.sh'; then
  warn "crontab missing run-daily-jobs.sh — run install-mac-job-agent-schedule.sh"
else
  if crontab -l | grep -E 'run-daily-jobs' | grep -qE '9,15|15,9'; then
    ok "cron has morning + afternoon daily (9 and 15)"
  else
    warn "cron run-daily-jobs not at both 9 and 15 — got: $(crontab -l | grep run-daily-jobs || echo none)"
  fi
fi

UID_NUM="$(id -u)"
if launchctl print "gui/${UID_NUM}/${LABEL}" &>/dev/null; then
  ok "LaunchAgent ${LABEL} loaded"
else
  warn "LaunchAgent ${LABEL} not loaded — sleep catch-up disabled"
fi

PYTHON="${ROOT}/.venv/bin/python3"
TWO_SLOT="${ROOT}/extras/daily_two_slot.py"
if [ -x "$PYTHON" ] && [ -f "$TWO_SLOT" ]; then
  plan="$("$PYTHON" "$TWO_SLOT" \
    --state-file "$STATE_FILE" \
    --morning-start-hour 9 --morning-start-minute 0 \
    --afternoon-start-hour 15 --afternoon-start-minute 0 \
    --dry-run -- \
    true 2>/dev/null || true)"
  ok "two-slot planner: $(echo "$plan" | python3 -c "import sys,json; d=json.load(sys.stdin); print('morning='+str(d.get('run_morning'))+', afternoon='+str(d.get('run_afternoon')))" 2>/dev/null || echo "$plan")"
else
  warn "cannot dry-run daily_two_slot.py"
fi

if [ -f "$STATE_FILE" ]; then
  ok "state file $(cat "$STATE_FILE" | tr -d '\n' | head -c 120)"
else
  ok "state file will be created on first run"
fi

exit "$ERR"
