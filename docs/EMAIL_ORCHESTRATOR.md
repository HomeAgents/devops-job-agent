# Email-driven job orchestrator

Multi-user job search via **genie4cv@gmail.com**: onboarding (CV + keywords), scheduled digests, feedback, and VM idle shutdown.

## Rollback tag

Before this feature:

```bash
git checkout pre-email-orchestrator-v1
```

Tag: **`pre-email-orchestrator-v1`** @ `64ed025`.

## Architecture

| Component | Role |
|-----------|------|
| `run_orchestrator.py poll-inbox` | IMAP unseen mail → conversation → optional job run |
| `run_orchestrator.py daily` | 09:00 batch from DB (`schedule_days`) |
| `orchestrator/user_db.py` | SQLite profiles per email |
| `orchestrator/conversation.py` | State machine + replies |
| `orchestrator/job_runner.py` | Per-user config + `run.py` (or Docker) |
| `scripts/run-daily-jobs.sh` | Single master cron entry |
| `scripts/poll-inbox.sh` | Every 5 min while VM is up |

## VM crontab (one file)

```bash
bash scripts/install-orchestrator-cron.sh
```

- **09:00** — all users due today (DB `schedule_days`)
- **\*/5** — poll inbox, reset idle timer, stop VM after 15 min quiet (`ORCHESTRATOR_VM_AUTOSTOP=1`)
- **19:00** — birthday / scoutsignal (existing)

## Email wake while VM is off

Deploy the Azure Function (timer + IMAP every 2 min):

```bash
cd infra/azure/email-wake-function && ./deploy.sh
```

See `infra/azure/email-wake-function/README.md`. Legacy Logic App / Automation notes: `infra/azure/email-wake-vm/README.md`.

## Setup on VM

```bash
cd ~/apps/devops-job-agent
cp orchestrator.env.example orchestrator.env   # fill Gmail App Password
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
bash scripts/install-orchestrator-cron.sh
# optional:
bash scripts/build-job-agent-image.sh
# set ORCHESTRATOR_USE_DOCKER=1 in orchestrator.env
```

## User flow (email)

1. **New user** → welcome + ask CV + keywords  
2. **Collecting** → ask missing fields  
3. **Keyword approval** → expanded EN + HE phrase list; reply `ALL`, `1,3,5`, or `EDIT: …`  
4. **Run** → job-agent digest (only after approval)  
5. **+30 min** → feedback email (**disabled** until `ORCHESTRATOR_FEEDBACK_ENABLED=1` and first digest sent)  
6. **Good feedback** → weekdays 09:00 default  
7. **Returning** → `1` same search · `2` new data · attach CV to replace/add  

## Docker (optional isolation)

```bash
docker run --rm -v ~/orchestrator-data/users/alice@example.com:/work \
  -e EMAIL_TO=alice@example.com job-agent:latest \
  --config /work/config.json --db /work/jobs.db --email-all-fetched
```

Set `ORCHESTRATOR_MAX_PARALLEL=2` on D2s_v3.

## Credentials

Gmail **App Password** for `genie4cv@gmail.com` (IMAP + SMTP).  
Job-agent send still uses `GENIE4CV_SETTINGS` / `EMAIL_TO` override per user.

# Email wake VM (Gmail → start vm-home-agents). See infra/azure/email-wake-function/README.md
