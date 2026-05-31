#!/usr/bin/env bash
# Mark morning or afternoon slot done in two-slot state (keeps cron + LaunchAgent in sync).
set -euo pipefail
export TZ="${TZ:-Asia/Jerusalem}"
SLOT="${1:-}"
STATE_FILE="${ORCHESTRATOR_DAILY_STATE_FILE:-${HOME}/orchestrator-data/.daily-two-slot-state.json}"
if [ -z "$SLOT" ]; then
  hour=$(date +%H)
  if [ "$hour" -lt 15 ]; then
    SLOT=morning
  else
    SLOT=afternoon
  fi
fi
case "$SLOT" in
  morning|afternoon|digest)
    ;;
  *)
    echo "usage: $0 [morning|afternoon|digest]" >&2
    exit 2
    ;;
esac
python3 - "$STATE_FILE" "$SLOT" <<'PY'
import json, os, sys, time
path, slot = sys.argv[1], sys.argv[2]
today = time.strftime("%Y-%m-%d", time.localtime())
data = {}
if os.path.isfile(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
if slot == "digest":
    data["morning_done_date"] = today
    data["afternoon_done_date"] = today
elif slot == "morning":
    data["morning_done_date"] = today
else:
    data["afternoon_done_date"] = today
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")
print(f"marked {slot} for {today} -> {path}")
PY
