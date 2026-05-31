#!/usr/bin/env bash
# Install Mac-primary crontab for all agents (no Azure runtime dependency)
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
BIRTHDAY="${HOME}/apps/birthday-copilot-agent"
TMP=$(mktemp)
{
  echo "CRON_TZ=Asia/Jerusalem"
  echo "25 8,18 * * * cd ${ROOT} && ./scripts/linkedin-home-workers-all.sh >>${HOME}/logs/linkedin-home-workers.log 2>&1"
  echo "50 8 * * * cd ${ROOT} && ./scripts/check-home-sync-health.sh >>${HOME}/logs/home-sync-health.log 2>&1"
  echo "52 8 * * * cd ${ROOT} && ./scripts/ensure-digest-remove-server.sh >>${HOME}/logs/digest-remove.log 2>&1"
  echo "0 9,19 * * * cd ${BIRTHDAY} && ./scripts/morning-agents-mac.sh >>${HOME}/logs/morning.log 2>&1"
  echo "0 9,17 * * * cd ${BIRTHDAY} && ./scripts/run-scoutsignal.sh >>${HOME}/logs/scoutsignal.log 2>&1"
  echo "5 9,15 * * * cd ${ROOT} && ./scripts/run-daily-jobs.sh >>${HOME}/logs/orchestrator-daily.log 2>&1"
  echo "20 9,15 * * * cd ${ROOT} && ./scripts/check-orchestrator-health.sh >>${HOME}/logs/orchestrator-health.log 2>&1"
  echo "*/5 * * * * cd ${ROOT} && ./scripts/poll-inbox.sh >>${HOME}/logs/orchestrator-poll.log 2>&1"
} > "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "Installed Mac cron:" && crontab -l
