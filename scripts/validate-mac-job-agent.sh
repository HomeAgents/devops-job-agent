#!/usr/bin/env bash
# Full Mac validation: permissions, remove stack, pytest, LinkedIn sync, dry-run digests.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
cd "$ROOT"
chmod 600 .env 2>/dev/null || true
chmod 600 "${HOME}/.job-agent/.digest-remove-secret" 2>/dev/null || true

echo "== 1/5 permissions =="
stat -f '%Sp %N' .env

echo "== 2/5 remove URL sync + server =="
./scripts/ensure-digest-remove-server.sh
grep '^ORCHESTRATOR_REMOVE_BASE_URL=' .env || true

echo "== 3/5 pytest + tunnel =="
RUN_DRY_JOB=0 ./scripts/test-job-agent-mac.sh

echo "== 4/5 LinkedIn home sync (all users) =="
./scripts/linkedin-home-workers-all.sh | tail -20

echo "== 5/5 dry-run digests =="
. .venv/bin/activate
for email in arkadiy.kats@gmail.com amnon.meron@gmail.com; do
  echo "--- $email ---"
  python3 run_orchestrator.py run-user --email "$email" --dry-run 2>&1 | tail -1
  head -2 "${ORCHESTRATOR_DATA_DIR:-${HOME}/orchestrator-data}/users/$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('$email'))")/last-run.log"
done

echo "== validate-mac-job-agent OK =="
