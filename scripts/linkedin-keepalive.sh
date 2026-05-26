#!/usr/bin/env bash
# Keep LinkedIn session alive with realistic human-like browsing.
# Run via cron every 3-4h: 0 */4 * * * /home/azureuser/apps/devops-job-agent/scripts/linkedin-keepalive.sh
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/linkedin-keepalive.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

export DISPLAY="${DISPLAY:-:1}"

python3 -c "
import sys, json
sys.path.insert(0, '.')
from job_agent.browser.session import linkedin_keepalive, linkedin_auto_login

with open('config.json') as f:
    cfg = json.load(f)

print('[keepalive] Starting human-like browsing session...')
if linkedin_keepalive(cfg, headless=True):
    print('[keepalive] Session alive — OK')
else:
    print('[keepalive] Session expired — attempting auto-login...')
    if linkedin_auto_login(cfg, headless=True):
        print('[keepalive] Auto-login succeeded')
    else:
        print('[keepalive] Auto-login failed — manual re-login needed')
        sys.exit(1)
" >>"$LOG" 2>&1

echo "[$(date -Iseconds)] keepalive done" >>"$LOG"
