#!/usr/bin/env bash
# Auto re-login to LinkedIn using stored credentials (headless).
# Called by morning-agents.sh or cron before the daily job alert run.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/linkedin-relogin.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

export DISPLAY="${DISPLAY:-:1}"

.venv/bin/python3 -c "
import sys, json
sys.path.insert(0, '.')
from job_agent.browser.session import ensure_linkedin_session

with open('config.json') as f:
    cfg = json.load(f)

if ensure_linkedin_session(cfg, headless=True):
    print('[relogin] LinkedIn session ready')
    sys.exit(0)
else:
    print('[relogin] All recovery attempts failed — manual login needed')
    sys.exit(1)
" >>"$LOG" 2>&1

RESULT=$?
echo "[$(date -Iseconds)] relogin result=$RESULT" >>"$LOG"
exit $RESULT
