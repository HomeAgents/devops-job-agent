#!/usr/bin/env bash
# Alert admin if today's daily or LinkedIn sync looks failed (Mac cron watchdog).
set -euo pipefail
export TZ="${TZ:-Asia/Jerusalem}"
ROOT="${HOME}/apps/devops-job-agent"
[ ! -d "$ROOT" ] && ROOT="${HOME}/devops-job-agent"
DATA="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
LOG_DIR="${HOME}/logs"
ADMIN="${ORCHESTRATOR_ADMIN_EMAIL:-arkadiy.kats@gmail.com}"
TODAY=$(date +%Y-%m-%d)
issues=()

daily_log="${LOG_DIR}/orchestrator-daily.log"
if [ -f "$daily_log" ]; then
  if ! grep -q "${TODAY}" "$daily_log" 2>/dev/null; then
    issues+=("no orchestrator-daily.log entries for ${TODAY}")
  fi
else
  issues+=("missing ${daily_log}")
fi

state="${DATA}/.daily-two-slot-state.json"
if [ -f "$state" ]; then
  if ! grep -q "\"morning_done_date\": \"${TODAY}\"" "$state" 2>/dev/null; then
    issues+=("morning daily slot not marked for ${TODAY}")
  fi
else
  issues+=("missing daily-two-slot state file")
fi

li_log="${LOG_DIR}/linkedin-home-workers.log"
if [ -f "$li_log" ]; then
  if ! grep -q "${TODAY}" "$li_log" 2>/dev/null; then
    issues+=("no LinkedIn home worker log for ${TODAY}")
  fi
fi

if ! pgrep -f "run.py --digest-remove-server" >/dev/null 2>&1; then
  issues+=("digest remove server not running")
fi

if [ "${#issues[@]}" -eq 0 ]; then
  echo "[$(date -Iseconds)] health OK"
  exit 0
fi

echo "[$(date -Iseconds)] health ISSUES: ${issues[*]}" >&2

# Email admin only once per day
stamp="${DATA}/.health-alert-${TODAY}.sent"
if [ -f "$stamp" ]; then
  exit 1
fi
touch "$stamp"

ISSUES_FILE="$(mktemp)"
printf '%s\n' "${issues[@]}" >"$ISSUES_FILE"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a
PYTHONPATH=. ADMIN_EMAIL="${ADMIN}" ISSUES_FILE="${ISSUES_FILE}" python3 <<'PY' || true
import os, smtplib
from email.message import EmailMessage
from pathlib import Path

from job_agent.settings import get_setting

admin = os.environ.get("ADMIN_EMAIL", "").strip()
issues = Path(os.environ["ISSUES_FILE"]).read_text(encoding="utf-8").strip().splitlines()
user = get_setting("EMAIL_USER", "GMAIL_EMAIL").strip()
password = get_setting("EMAIL_PASS", "GMAIL_PASSWORD").strip()
if not (admin and user and password and issues):
    raise SystemExit("skip email")
body = "Job Agent health check found issues:\n\n" + "\n".join(f"- {x}" for x in issues)
msg = EmailMessage()
msg["Subject"] = "Job Agent: Mac health check — action needed"
msg["From"] = user
msg["To"] = admin
msg.set_content(body)
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(user, password)
    s.send_message(msg)
print("Sent health alert to", admin)
PY
rm -f "$ISSUES_FILE"
exit 1
