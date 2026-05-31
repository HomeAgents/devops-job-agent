#!/usr/bin/env bash
# Home LinkedIn export for every orchestrator user (from DB). No per-user shell setup by subscribers.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -d .venv ] && . .venv/bin/activate
[ -f .env ] && set -a && . .env && set +a

FOUND=0
while IFS= read -r email; do
  [ -z "$email" ] && continue
  FOUND=1
  echo "=== home worker: ${email} ==="
  if USER_EMAIL="$email" "$ROOT/scripts/linkedin-home-worker.sh"; then
    continue
  fi
  echo "WARN: LinkedIn sync failed for ${email} — digest still uses Greenhouse/ATS; admin can add credentials in orchestrator-data/users/$(PYTHONPATH=. python3 -c "from orchestrator.user_db import sanitize_email; print(sanitize_email('${email}'))")/linkedin.env" >&2
done < <(PYTHONPATH=. python3 -c "
from orchestrator.linkedin_home_users import users_for_home_linkedin_sync
for e in users_for_home_linkedin_sync():
    print(e)
")
if [ "$FOUND" -eq 0 ]; then
  echo "[$(date -Iseconds)] no orchestrator users need LinkedIn home sync" >&2
fi
exit 0
