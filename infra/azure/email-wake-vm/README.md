# Email → wake VM

## Current production setup (May 2026)

| Component | Status |
|-----------|--------|
| **Gmail OAuth** (`gmail-genie4cv`) | Connected |
| **`la-start-home-agents-vm`** | Enabled — HTTP callback starts the VM (tested) |
| **`poll-inbox` cron on VM** | Every 5 min while VM is running |
| **`ORCHESTRATOR_VM_AUTOSTOP=0`** | VM stays up so cron keeps polling |

### Gmail + VM in one Logic App?

**Not for `@gmail.com` consumer accounts.** Google policy blocks HTTP / Start VM in the same workflow as the Gmail connector. Options later: [Bring your own Google OAuth app](https://learn.microsoft.com/azure/connectors/connectors-google-data-security-privacy-policy) or an Azure Function with IMAP.

### Email wake while VM is off

**Production:** Azure Function `func-email-wake-home-agents` — timer + IMAP every 2 min → start VM.

```bash
cd infra/azure/email-wake-function && ./deploy.sh
```

See `infra/azure/email-wake-function/README.md`.

Legacy options (partial / blocked):

- **`la-start-home-agents-vm`** — HTTP callback starts VM (used as Function fallback)
- **`la-email-wake-home-agents`** (Gmail+HTTP) — blocked for consumer `@gmail.com` without BYO Google OAuth
- **Automation IMAP runbook** — outbound 993 blocked in sandbox

## One-time deploy (Cloud Shell or any `az login`)

```bash
cd infra/azure/email-wake-vm
./deploy-finished.sh
```

Gmail OAuth: [Portal → gmail-genie4cv](https://portal.azure.com/#resource/subscriptions/40f9da3f-642b-4815-9af4-4556e9114038/resourceGroups/rg-home-agents/providers/Microsoft.Web/connections/gmail-genie4cv/overview)

## Flow (VM running)

```
Email → genie4cv@gmail.com
    ↓
VM poll-inbox (every 5 min) → reply / job search
```

## Files

- `logic-app-start-vm-only.json` — HTTP Logic App to start VM
- `logic-app-email-wake.json` — Gmail+HTTP (blocked for consumer Gmail; needs BYO Google app)
- `deploy-finished.sh` — post-OAuth enable script
- `Wake-HomeAgentsOnEmail.ps1` — Automation IMAP attempt (outbound 993 blocked in sandbox)
