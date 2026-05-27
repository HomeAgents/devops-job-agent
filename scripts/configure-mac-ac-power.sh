#!/usr/bin/env bash
# Keep Mac awake on wall power for home LinkedIn worker; allow display sleep / screen saver only.
#
# Run once (admin password):
#   ./scripts/configure-mac-ac-power.sh
#
# Revert battery profile is unchanged. Only AC Power (-c) is tuned.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

DISPLAY_SLEEP_MIN="${DISPLAY_SLEEP_MIN:-30}"

echo "Current AC power settings:"
pmset -g custom 2>/dev/null | sed -n '/AC Power:/,/Battery Power:/p' || pmset -g

echo ""
echo "Applying AC (charger) profile:"
echo "  - System sleep: NEVER (apps/cron/network stay alive)"
echo "  - Display sleep: ${DISPLAY_SLEEP_MIN} minutes (screen may turn off / screen saver)"
echo "  - Disk sleep: off"
echo "  - Standby: off"
echo ""

sudo pmset -c sleep 0
sudo pmset -c disksleep 0
sudo pmset -c standby 0
sudo pmset -c displaysleep "${DISPLAY_SLEEP_MIN}"
sudo pmset -c powernap 1
sudo pmset -c womp 1
sudo pmset -c ttyskeepawake 1
sudo pmset -c tcpkeepalive 1

# Optional: disable auto-logout if set (rare on personal Macs).
if defaults read /Library/Preferences/.GlobalPreferences com.apple.autologout.AutoLogOutDelay &>/dev/null; then
  echo "Disabling scheduled auto-logout..."
  sudo defaults delete /Library/Preferences/.GlobalPreferences com.apple.autologout.AutoLogOutDelay 2>/dev/null || true
fi

echo ""
echo "Done. New AC profile:"
pmset -g custom 2>/dev/null | sed -n '/AC Power:/,/Battery Power:/p' || pmset -g

echo ""
echo "Tip: scheduled LinkedIn export uses caffeinate during the run so it finishes even if"
echo "     the display is off. Install LaunchAgent: extras/com.job-agent.linkedin-home.plist"
