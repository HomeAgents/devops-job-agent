#!/usr/bin/env bash
# Install master crontab: birthday 9:00/19:00, ScoutSignal 9:15/19:15, job agent, inbox poll.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
BIRTHDAY="${HOME}/apps/birthday-copilot-agent"
CRON_TMP=$(mktemp)
{
  echo "CRON_TZ=Asia/Jerusalem"
  echo "@reboot ${ROOT}/scripts/vm-boot-agents.sh"
  echo "0 9 * * * ${BIRTHDAY}/scripts/morning-agents.sh"
  echo "15 9 * * * ${BIRTHDAY}/scripts/run-scoutsignal.sh"
  echo "5 9 * * * ${ROOT}/scripts/run-daily-jobs.sh"
  echo "*/5 * * * * ${ROOT}/scripts/poll-inbox.sh"
  echo "0 19 * * * ${BIRTHDAY}/scripts/morning-agents.sh"
  echo "15 19 * * * ${BIRTHDAY}/scripts/run-scoutsignal.sh"
} > "$CRON_TMP"
crontab "$CRON_TMP"
rm -f "$CRON_TMP"
echo "Installed crontab:"
crontab -l
