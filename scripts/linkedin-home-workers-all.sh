#!/usr/bin/env bash
# Run home LinkedIn export for all orchestrator users (set USER_EMAILS or defaults).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_EMAILS="${USER_EMAILS:-arkadiy.kats@gmail.com amnon.meron@gmail.com}"
for email in $USER_EMAILS; do
  echo "=== home worker: ${email} ==="
  USER_EMAIL="$email" "$ROOT/scripts/linkedin-home-worker.sh"
done
