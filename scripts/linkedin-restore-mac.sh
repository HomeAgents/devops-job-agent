#!/usr/bin/env bash
# Admin only: LinkedIn login + home sync for one user (subscribers use email only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_EMAIL="${USER_EMAIL:-arkadiy.kats@gmail.com}"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

SAFE="$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${USER_EMAIL}'))")"
export JOB_AGENT_CONFIG="${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}/users/${SAFE}/config.json"
if [ ! -f "$JOB_AGENT_CONFIG" ]; then
  export JOB_AGENT_CONFIG="${ROOT}/config.json"
fi

TMP_CFG="/tmp/job-agent-restore-${SAFE}.json"
PYTHONPATH=. python3 -c "
import json
from pathlib import Path
src = Path('${JOB_AGENT_CONFIG}')
cfg = json.loads(src.read_text(encoding='utf-8'))
cfg.setdefault('browser', {})['user_data_dir'] = str(Path.home() / '.job-agent/home-users/${SAFE}/browser')
cfg['_user_email'] = '${USER_EMAIL}'.strip().lower()
Path('${TMP_CFG}').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
"
export JOB_AGENT_CONFIG="$TMP_CFG"

echo "=== Step 1: LinkedIn login (browser window) ==="
echo "Profile: ~/.job-agent/home-users/${SAFE}/browser"
python3 run.py --linkedin-login

echo ""
echo "=== Step 2: Home sync export ==="
USER_EMAIL="${USER_EMAIL}" "$ROOT/scripts/linkedin-home-worker.sh"
echo ""
echo "Done. Daily digests will use LinkedIn from ${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}/users/${SAFE}/linkedin_home/jobs.json"
