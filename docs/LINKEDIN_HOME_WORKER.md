# LinkedIn home worker (residential IP)

LinkedIn often blocks the Azure VM IP on `/jobs/search` even when `/feed` works.  
Run LinkedIn scraping on a **home Mac/PC** and sync results to the VM.

## Architecture

```
Home Mac (residential IP)
  playwright + linkedin login
  run.py --linkedin-home-export  →  jobs.json
  scp → VM ~/orchestrator-data/users/<email>/linkedin_home/jobs.json

Azure VM (orchestrator)
  daily run reads fresh jobs.json
  adds as "LinkedIn (home sync)"
  skips VM LinkedIn browser when sync is fresh (optional)
```

## Mac worker (automatic for all orchestrator users)

Cron runs `linkedin-home-workers-all.sh`, which reads **every active user** from `orchestrator.db` (no manual `USER_EMAIL` list). Subscribers only use **email**; they never run scripts.

```bash
# Cron (via install-mac-all-agents-cron.sh): 08:25 and 18:25
./scripts/linkedin-home-workers-all.sh
# Or:
python3 run_orchestrator.py linkedin-home-sync
```

### One LinkedIn login for everyone (default)

Set in `.env` (or `orchestrator.env`):

```bash
ORCHESTRATOR_LINKEDIN_SHARED_SESSION=1
ORCHESTRATOR_LINKEDIN_OWNER_EMAIL=arkadiy.kats@gmail.com
```

Cron runs **Amnon’s keywords**, **your keywords**, etc., using **your** logged-in browser session. Reach-out / network features stay off on export. Each user still gets their own `linkedin_home/jobs.json`.

### Admin only (once for the owner account)

```bash
python3 run_orchestrator.py linkedin-bootstrap --email arkadiy.kats@gmail.com
```

Optional: `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` in project `.env` for auto-login. Per-user `linkedin.env` is only needed if `ORCHESTRATOR_LINKEDIN_SHARED_SESSION=0`.

## Schedule on Mac (cron)

Twice daily before VM digest (e.g. 08:30 and 18:30 Israel time):

```cron
30 8,18 * * * cd ~/apps/devops-job-agent && VM_HOST=20.217.203.43 USER_EMAIL=arkadiy.kats@gmail.com ./scripts/linkedin-home-worker.sh >>~/logs/linkedin-home-worker.log 2>&1
```

## VM config (per user `config.json`)

Orchestrator `build_user_config` can add:

```json
"linkedin": {
  "home_sync": {
    "enabled": true,
    "max_age_hours": 18,
    "skip_vm_linkedin_when_fresh": true
  }
}
```

Import path defaults to `~/orchestrator-data/users/<email>/linkedin_home/jobs.json`.

## Verify on VM

```bash
./scripts/linkedin-import-home-sync.sh arkadiy.kats@gmail.com
```
