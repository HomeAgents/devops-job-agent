#!/usr/bin/env bash
# Mac: LaunchAgent for digest remove server + cloudflared tunnel; sync public URL to .env.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
if [ ! -d "$ROOT" ]; then
  ROOT="${HOME}/devops-job-agent"
fi
LA="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/logs"
mkdir -p "$LOG_DIR" "${HOME}/.job-agent"

install_plist() {
  local src="$1" name="$2"
  local dst="${LA}/${name}.plist"
  sed "s|/Users/arkadiykats|${HOME}|g" "$src" >"$dst"
  launchctl bootout "gui/$(id -u)/${name}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dst"
  echo "Loaded ${name}"
}

install_plist "${ROOT}/extras/com.job-agent.remove-server.example.plist" "com.job-agent.remove-server"

launchctl bootout "gui/$(id -u)/com.job-agent.cloudflared-remove" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.job-agent.cloudflared-named" 2>/dev/null || true
if [ -f "${ROOT}/.env" ]; then
  set -a && . "${ROOT}/.env" && set +a
fi
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  dst="${LA}/com.job-agent.cloudflared-named.plist"
  sed "s|/Users/arkadiykats|${HOME}|g; s|CLOUDFLARE_TUNNEL_TOKEN_PLACEHOLDER|${CLOUDFLARE_TUNNEL_TOKEN}|" \
    "${ROOT}/extras/com.job-agent.cloudflared-named.example.plist" >"$dst"
  launchctl bootstrap "gui/$(id -u)" "$dst"
  echo "Loaded com.job-agent.cloudflared-named (stable tunnel)"
else
  install_plist "${ROOT}/extras/com.job-agent.cloudflared-remove.example.plist" "com.job-agent.cloudflared-remove"
  echo "Loaded com.job-agent.cloudflared-remove (quick tunnel — URL may change on reboot)"
fi

sleep 4
"${ROOT}/scripts/sync-remove-base-url.sh" || true
"${ROOT}/scripts/ensure-digest-remove-server.sh"
echo "Remove stack installed. Verify: ${ROOT}/scripts/test-job-agent-mac.sh"
