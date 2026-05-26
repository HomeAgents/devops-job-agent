#!/usr/bin/env bash
# Keep LinkedIn session alive by briefly visiting a page.
# Run via cron every 6h: 0 */6 * * * /home/azureuser/apps/devops-job-agent/scripts/linkedin-keepalive.sh
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/linkedin-keepalive.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

export DISPLAY="${DISPLAY:-:1}"

python3 -c "
import sys, time, json
sys.path.insert(0, '.')
from job_agent.browser.session import _launch_persistent, _page_looks_logged_in, _safe_close

with open('config.json') as f:
    cfg = json.load(f)

print('[keepalive] Launching browser...')
pw, context = _launch_persistent(cfg, headless=True, service='linkedin')
try:
    page = context.pages[0] if context.pages else context.new_page()
    page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=60000)
    time.sleep(3)
    if _page_looks_logged_in(page):
        print('[keepalive] Session alive — OK')
    else:
        print('[keepalive] Session expired — needs re-login')
        sys.exit(1)
finally:
    _safe_close(context, pw)
" >>"$LOG" 2>&1

echo "[$(date -Iseconds)] keepalive done" >>"$LOG"
