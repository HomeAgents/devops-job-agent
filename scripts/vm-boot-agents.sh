#!/usr/bin/env bash
# Run after vm-home-agents starts (cron @reboot or manual).
set -euo pipefail
export TZ=Asia/Jerusalem
mkdir -p "${HOME}/logs"

if command -v az >/dev/null 2>&1; then
  az login --identity --allow-no-subscriptions >/dev/null 2>&1 || true
fi

JOB_ROOT="${HOME}/apps/devops-job-agent"
if [[ -x "${JOB_ROOT}/scripts/digest-remove-server.sh" ]]; then
  if ! pgrep -f "run.py --digest-remove-server" >/dev/null 2>&1; then
    nohup bash "${JOB_ROOT}/scripts/digest-remove-server.sh" arkadiy.kats@gmail.com \
      >>"${HOME}/logs/digest-remove-server.log" 2>&1 &
  fi
fi

if systemctl --user is-enabled birthday-copilot.service >/dev/null 2>&1; then
  systemctl --user start birthday-copilot.service 2>/dev/null || true
fi

echo "[$(date -Iseconds)] vm-boot-agents done" >>"${HOME}/logs/vm-boot.log"
