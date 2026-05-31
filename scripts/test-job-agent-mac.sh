#!/usr/bin/env bash
# Mac smoke test: unit tests, digest remove server, public tunnel probe, optional dry-run.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
cd "$ROOT"
PYTHON="${ROOT}/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "Missing venv at ${ROOT}/.venv" >&2
  exit 1
fi
[ -f .env ] && set -a && . .env && set +a

echo "== pytest =="
"$PYTHON" -m pytest tests/ -q --tb=line

echo "== digest remove server =="
"$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from orchestrator.digest_server import ensure_shared_remove_server
sys.exit(0 if ensure_shared_remove_server() else 1)
"

if [ -x "${ROOT}/scripts/sync-remove-base-url.sh" ]; then
  "${ROOT}/scripts/sync-remove-base-url.sh" 2>/dev/null || true
  [ -f .env ] && set -a && . .env && set +a
fi

BASE="${ORCHESTRATOR_REMOVE_BASE_URL:-}"
if [ -z "$BASE" ]; then
  echo "ORCHESTRATOR_REMOVE_BASE_URL not set — skip tunnel probe" >&2
else
  echo "== tunnel probe ($BASE) =="
  code=$(curl -sS -o /dev/null -w "%{http_code}" "${BASE%/}/status" || echo "000")
  if [ "$code" = "400" ] || [ "$code" = "200" ]; then
    echo "tunnel OK (HTTP $code)"
  else
    echo "tunnel probe failed HTTP $code — restart cloudflared and update .env" >&2
    exit 1
  fi
fi

EMAIL="${1:-arkadiy.kats@gmail.com}"
if [ "${RUN_DRY_JOB:-0}" = "1" ]; then
  echo "== dry-run job for $EMAIL =="
  "$PYTHON" run_orchestrator.py run-user --email "$EMAIL" --dry-run
fi

echo "== Mac smoke test OK =="
