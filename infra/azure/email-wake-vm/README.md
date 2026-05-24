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

Until a Gmail→wake Function is added, either:

- Keep VM running (`ORCHESTRATOR_VM_AUTOSTOP=0`), or  
- Manually start VM, or POST to `la-start-home-agents-vm` callback (stored in Automation variable `OrchestratorWakeLogicAppUrl`).

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
