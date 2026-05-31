#!/usr/bin/env bash
# Mac Job Agent: cron 09:05 + 15:05 + LaunchAgent two-slot catch-up (like ScoutSignal).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HOME}"
LABEL="com.devops-job-agent.daily-two-slot"
PLIST_SRC="${ROOT}/scripts/com.devops-job-agent.daily-two-slot.plist"
PLIST_DST="${HOME_DIR}/Library/LaunchAgents/${LABEL}.plist"

chmod +x "${ROOT}/scripts/run-daily-jobs.sh" \
  "${ROOT}/scripts/run-daily-jobs-once.sh" \
  "${ROOT}/scripts/orchestrator-daily-catchup.sh" \
  "${ROOT}/scripts/mark-orchestrator-daily-slot.sh"

# Update shared Mac crontab (LinkedIn, poll, birthday, scout, job agent 9+15)
bash "${ROOT}/scripts/install-mac-all-agents-cron.sh"

sed "s|HOME_PLACEHOLDER|${HOME_DIR}|g; s|ROOT_PLACEHOLDER|${ROOT}|g" "$PLIST_SRC" >"$PLIST_DST"
UID_NUM="$(id -u)"
if launchctl print "gui/${UID_NUM}/${LABEL}" &>/dev/null; then
  launchctl bootout "gui/${UID_NUM}" "$PLIST_DST" 2>/dev/null || true
fi
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST"
launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true

echo ""
echo "=== Job Agent daily schedule (Mac) ==="
echo "Cron (exact times — Mac must be awake at tick):"
crontab -l | grep -E 'run-daily-jobs|orchestrator-daily' || true
echo ""
echo "LaunchAgent (sleep catch-up): ${LABEL}"
echo "  Morning slot: from 09:00"
echo "  Afternoon slot: from 15:00"
echo "  Poll: every 30 minutes while Mac is awake"
echo ""
echo "State: ${HOME_DIR}/orchestrator-data/.daily-two-slot-state.json"
echo "Logs:"
echo "  ${HOME_DIR}/logs/orchestrator-daily-YYYYMMDD-{morning|afternoon}.log"
echo "  ${HOME_DIR}/logs/orchestrator-daily-two-slot.log"
echo ""
"${ROOT}/scripts/validate-orchestrator-daily-schedule.sh"
