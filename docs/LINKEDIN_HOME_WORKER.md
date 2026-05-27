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

## One-time setup (home machine)

1. Clone/sync `devops-job-agent` (same version as VM).
2. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. `playwright install chromium`
4. Set `.env` with `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD`.
5. `python3 run.py --linkedin-login` (complete login in browser once).

## Run manually

```bash
export VM_HOST=20.217.203.43
export VM_USER=azureuser
export USER_EMAIL=arkadiy.kats@gmail.com
./scripts/linkedin-home-worker.sh
```

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
