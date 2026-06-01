#!/usr/bin/env bash
# Kill stale remove-server / cloudflared on :8791 and restart LaunchAgents + sync tunnel URL.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
[ ! -d "$ROOT" ] && ROOT="${HOME}/devops-job-agent"

echo "Stopping stale processes on port 8791..."
for pid in $(lsof -ti :8791 2>/dev/null || true); do
  kill "$pid" 2>/dev/null || true
done
sleep 1
for pid in $(lsof -ti :8791 2>/dev/null || true); do
  kill -9 "$pid" 2>/dev/null || true
done

pkill -f "cloudflared tunnel.*127.0.0.1:8791" 2>/dev/null || true
pkill -f "run.py --digest-remove-server" 2>/dev/null || true
sleep 2

"${ROOT}/scripts/install-mac-remove-stack.sh"
sleep 3
"${ROOT}/scripts/sync-remove-base-url.sh"
echo "Tunnel URL: $(grep '^ORCHESTRATOR_REMOVE_BASE_URL=' "${ROOT}/.env" 2>/dev/null || echo '(not set)')"
curl -s -o /dev/null -w "Probe /status: HTTP %{http_code}\n" --max-time 12 "$(grep '^ORCHESTRATOR_REMOVE_BASE_URL=' "${ROOT}/.env" | cut -d= -f2-)/status" || true
