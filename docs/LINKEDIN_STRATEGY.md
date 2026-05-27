# LinkedIn strategy (stable)

LinkedIn **blocks the Azure VM IP** on job search. VM login/keepalive/scraping will keep failing.

## Architecture (final)

| Where | Role |
|-------|------|
| **Mac (home IP)** | Only place that scrapes LinkedIn (`linkedin-home-worker.sh`) |
| **VM** | Imports `jobs.json`, sends digest — **never** opens LinkedIn browser |

## Daily timeline (Israel)

| Time | What |
|------|------|
| 08:25 | Mac: `linkedin-home-workers-all.sh` (all users) |
| 08:50 | Azure Logic App starts VM |
| 08:50 | VM: `check-home-sync-health.sh` |
| 09:05 | VM: daily digest |

## Per user setup (once)

```bash
cd ~/devops-job-agent && source .venv/bin/activate
USER_EMAIL=you@gmail.com python3 run.py --linkedin-login
# Optional: .env.home.<safe> with LINKEDIN_EMAIL / LINKEDIN_PASSWORD
USER_EMAIL=you@gmail.com ./scripts/linkedin-home-worker.sh
```

## If LinkedIn is empty in email

1. Mac was asleep at 08:25 → run worker manually.
2. Stale file → still used up to **36h** (stale fallback); re-run worker for fresh jobs.
3. Amnon needs **his own** Mac login (separate browser profile under `~/.job-agent/home-users/...`).

## Mac on power 24/7 (screen off OK, do not sleep system)

When plugged in, macOS was sleeping the **whole Mac** after 30 minutes — that stops cron and LinkedIn.

**One-time (admin):**

```bash
cd ~/devops-job-agent
chmod +x scripts/configure-mac-ac-power.sh
./scripts/configure-mac-ac-power.sh
```

This sets on **AC power only**:

| Setting | Value |
|---------|--------|
| System sleep | Never |
| Display sleep | 30 min (screen saver / lock OK) |
| Disk / standby | Off |

The home worker also runs under `caffeinate` during export so the scrape finishes even if the display is off.

**LaunchAgent (scheduled export):**

```bash
cp extras/com.job-agent.linkedin-home.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.job-agent.linkedin-home.plist
```

## VM LinkedIn disabled

`linkedin.home_sync.disable_vm_linkedin_browser: true` (default for orchestrator users).
