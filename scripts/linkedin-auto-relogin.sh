#!/usr/bin/env bash
# Auto re-login to LinkedIn if session is expired and VNC display is available.
# Called by morning-agents.sh or cron before the job alert runs.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
LOG="${HOME}/logs/linkedin-relogin.log"
mkdir -p "${HOME}/logs"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

export DISPLAY="${DISPLAY:-:1}"

# First check if session is still valid (headless, fast)
SESSION_OK=$(.venv/bin/python3 -c "
import sys, json
sys.path.insert(0, '.')
from job_agent.browser.session import linkedin_session_ready
with open('config.json') as f:
    cfg = json.load(f)
print('1' if linkedin_session_ready(cfg, headless=True) else '0')
" 2>/dev/null || echo "0")

if [ "$SESSION_OK" = "1" ]; then
  echo "[$(date -Iseconds)] LinkedIn session OK — no re-login needed" >>"$LOG"
  exit 0
fi

echo "[$(date -Iseconds)] LinkedIn session expired — attempting auto-relogin..." >>"$LOG"

# Check if VNC display is available
if ! xdpyinfo -display :1 >/dev/null 2>&1; then
  echo "[$(date -Iseconds)] No display :1 available. Starting VNC..." >>"$LOG"
  vncserver :1 -geometry 1280x800 -depth 24 >/dev/null 2>&1 || true
  sleep 2
fi

# Try headed login (will show on VNC display :1)
# Uses saved credentials from the browser profile (auto-fill)
.venv/bin/python3 -c "
import sys, time, json
sys.path.insert(0, '.')
from job_agent.browser.session import _launch_persistent, _page_looks_logged_in, _safe_close

with open('config.json') as f:
    cfg = json.load(f)

pw, context = _launch_persistent(cfg, headless=False, service='linkedin')
try:
    page = context.pages[0] if context.pages else context.new_page()
    page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded', timeout=60000)
    time.sleep(5)

    # If the page auto-logged-in (saved credentials), we're done
    if _page_looks_logged_in(page):
        print('[relogin] Auto-login successful (saved credentials)')
        sys.exit(0)

    # Navigate to feed to trigger any saved session
    page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=60000)
    time.sleep(5)
    if _page_looks_logged_in(page):
        print('[relogin] Session restored from profile')
        sys.exit(0)

    print('[relogin] Could not auto-login — manual VNC login needed')
    sys.exit(1)
finally:
    _safe_close(context, pw)
" >>"$LOG" 2>&1

RESULT=$?
if [ $RESULT -eq 0 ]; then
  echo "[$(date -Iseconds)] Re-login successful" >>"$LOG"
else
  echo "[$(date -Iseconds)] Re-login failed — manual intervention needed" >>"$LOG"
fi
exit $RESULT
