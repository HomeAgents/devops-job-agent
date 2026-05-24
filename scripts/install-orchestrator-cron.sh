#!/usr/bin/env bash
# Install master crontab: 9:00 daily batch + inbox poll every 5 min while VM is up.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
CRON_TMP=$(mktemp)
{
  echo "CRON_TZ=Asia/Jerusalem"
  echo "@reboot ${HOME}/apps/devops-job-agent/scripts/vm-boot-agents.sh"
  echo "0 9 * * * ${HOME}/apps/birthday-copilot-agent/scripts/morning-agents.sh"
  echo "5 9 * * * ${ROOT}/scripts/run-daily-jobs.sh"
  echo "*/5 * * * * ${ROOT}/scripts/poll-inbox.sh"
  echo "0 19 * * * ${HOME}/apps/birthday-copilot-agent/scripts/morning-agents.sh"
} > "$CRON_TMP"
crontab "$CRON_TMP"
rm -f "$CRON_TMP"
echo "Installed crontab:"
crontab -l
