#!/usr/bin/env bash
# Persist ORCHESTRATOR_REMOVE_BASE_URL from cloudflared quick-tunnel log → .env + all user configs.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
DATA="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}"
URL_FILE="${HOME}/.job-agent/remove-tunnel-url.txt"
LOG="${HOME}/logs/digest-remove-cloudflared.log"
ENV_FILE="${ROOT}/.env"

BASE="${1:-}"
# Log wins over stale url file (quick tunnel URL changes whenever cloudflared restarts).
if [ -z "$BASE" ] && [ -f "$LOG" ]; then
  BASE="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | tail -1 || true)"
fi
if [ -z "$BASE" ]; then
  if [ -f "$URL_FILE" ]; then
    BASE="$(tr -d '[:space:]' <"$URL_FILE")"
  fi
fi
if [ -z "$BASE" ]; then
  echo "No tunnel URL — start cloudflared or pass URL as arg" >&2
  exit 1
fi
BASE="${BASE%/}"
mkdir -p "${HOME}/.job-agent"
echo "$BASE" >"$URL_FILE"

PYTHON="${ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

"$PYTHON" <<PY
import json, os, re
from pathlib import Path

base = "${BASE}".rstrip("/")
root = Path("${ROOT}")
env = root / ".env"
if env.is_file():
    text = env.read_text(encoding="utf-8")
    if re.search(r"^ORCHESTRATOR_REMOVE_BASE_URL=", text, re.M):
        text = re.sub(
            r"^ORCHESTRATOR_REMOVE_BASE_URL=.*$",
            f"ORCHESTRATOR_REMOVE_BASE_URL={base}",
            text,
            count=1,
            flags=re.M,
        )
    else:
        text = text.rstrip() + f"\nORCHESTRATOR_REMOVE_BASE_URL={base}\n"
    env.write_text(text, encoding="utf-8")
    os.chmod(env, 0o600)

data = Path("${DATA}") / "users"
n = 0
for cfg in data.glob("*/config.json"):
    try:
        doc = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    dr = doc.setdefault("digest_remove", {})
    if not isinstance(dr, dict):
        continue
    dr["enabled"] = True
    dr["base_url"] = base
    cfg.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n += 1
print(f"Synced remove base URL to .env and {n} user config(s): {base}")
PY
