# Email wake — Azure Function (production)

Always-on **timer + IMAP** in Azure (no VM required). When actionable mail waits in **genie4cv@gmail.com** and **vm-home-agents** is off, the function starts the VM. The VM cron runs `poll-inbox`, replies, then deallocates after **15 min** idle (`ORCHESTRATOR_VM_AUTOSTOP=1`).

## Flow

```
Gmail UNSEEN (every 2 min, Azure Function)
    → filter (same rules as orchestrator/email_filters.py)
    → start VM (Managed Identity → ARM, or Logic App callback fallback)
    ↓
VM boots → cron poll-inbox */5 → reply / jobs
    → 15 min idle → az vm deallocate
```

## Deploy (once)

```bash
cd infra/azure/email-wake-function
chmod +x deploy.sh
./deploy.sh
```

Requires `az login`. Reads Gmail app password from VM `~/apps/devops-job-agent/.env` (`EMAIL_PASS`) unless `GMAIL_APP_PASSWORD` is set.

Also ensures `la-start-home-agents-vm` exists as optional fallback (`WAKE_LOGIC_APP_URL`).

## VM settings (after deploy)

On **vm-home-agents** in `orchestrator.env`:

```bash
ORCHESTRATOR_VM_AUTOSTOP=1
ORCHESTRATOR_IDLE_MINUTES=15
ORCHESTRATOR_REMOVE_BASE_URL=http://20.217.203.43:8791
ORCHESTRATOR_REMOVE_SECRET=<same-as-before>
```

Restart digest-remove server and confirm cron:

```bash
bash scripts/install-orchestrator-cron.sh
```

## Monitor

- Function → **Monitor** → `email_wake` invocations
- Logs should show `email_wake: {'actionable_unseen': ...}`

## Files

| File | Role |
|------|------|
| `function_app.py` | Timer trigger every 2 minutes |
| `orchestrator/wake_poll.py` | IMAP UNSEEN + ARM start VM (shared with tests) |
| `deploy.sh` | Create Function App, MI, publish zip |

## Why not Automation runbook?

Automation sandbox blocks outbound IMAP (port 993). Azure Functions allow IMAP and use the same filters as the orchestrator.
