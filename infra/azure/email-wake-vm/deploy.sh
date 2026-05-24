#!/usr/bin/env bash
# Deploy Gmail → wake VM: Logic App + Azure Automation IMAP poll (fallback).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG="${AZURE_RG:-rg-home-agents}"
AA="${AZURE_AUTOMATION_ACCOUNT:-aa-home-agents}"
LOCATION="${AZURE_LOCATION:-israelcentral}"
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
VM_SSH="${VM_AGENT_SSH:-azureuser@20.217.203.43}"
RUNBOOK="Wake-HomeAgentsOnEmail"
SCHEDULE="sched-email-wake-every-2m"
VAR_NAME="Genie4cvGmailAppPassword"

echo "==> Deploy Logic App (Gmail trigger → Start VM)"
az deployment group create \
  --resource-group "$RG" \
  --template-file "$ROOT/logic-app-email-wake.json" \
  --parameters subscriptionId="$SUBSCRIPTION_ID" \
  --output table

LA_PRINCIPAL="$(az logic workflow show -g "$RG" -n la-email-wake-home-agents --query identity.principalId -o tsv)"
echo "Logic App principal: $LA_PRINCIPAL"

echo ""
echo "==> Publish Azure Automation runbook (IMAP poll fallback, every 2 min)"
az automation runbook create \
  --resource-group "$RG" \
  --automation-account-name "$AA" \
  --name "$RUNBOOK" \
  --location "$LOCATION" \
  --runbook-type PowerShell \
  --description "Poll genie4cv Gmail; start vm-home-agents when user mail is waiting." \
  2>/dev/null || true

az automation runbook replace-content \
  --resource-group "$RG" \
  --automation-account-name "$AA" \
  --name "$RUNBOOK" \
  --content @"$ROOT/Wake-HomeAgentsOnEmail.ps1"

az automation runbook publish \
  --resource-group "$RG" \
  --automation-account-name "$AA" \
  --name "$RUNBOOK"

if ! az automation variable show -g "$RG" --automation-account-name "$AA" -n "$VAR_NAME" &>/dev/null; then
  echo "Creating encrypted Automation variable $VAR_NAME from VM .env (not printed)..."
  APP_PASS="$(ssh -o ConnectTimeout=15 "$VM_SSH" "grep '^EMAIL_PASS=' ~/apps/devops-job-agent/.env | cut -d= -f2-")"
  if [[ -z "$APP_PASS" ]]; then
    echo "ERROR: Could not read EMAIL_PASS from VM. Create variable manually:" >&2
    echo "  az automation variable create -g $RG --automation-account-name $AA -n $VAR_NAME --value '<app-password>' --encrypted true" >&2
    exit 1
  fi
  az automation variable create \
    --resource-group "$RG" \
    --automation-account-name "$AA" \
    --name "$VAR_NAME" \
    --value "$APP_PASS" \
    --encrypted true \
    --description "Gmail app password for genie4cv@gmail.com IMAP wake poll"
else
  echo "Automation variable $VAR_NAME already exists — leaving unchanged."
fi

# Import Az.Accounts + Az.Compute for runbook (if not already).
for mod in Az.Accounts Az.Compute; do
  az automation module create \
    --resource-group "$RG" \
    --automation-account-name "$AA" \
    --name "$mod" \
    --content-link uri="https://www.powershellgallery.com/api/v2/package/$mod" \
    2>/dev/null || true
done

START="$(python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"
EXPIRY="2031-12-31T23:59:00Z"

az automation schedule create \
  --resource-group "$RG" \
  --automation-account-name "$AA" \
  --name "$SCHEDULE" \
  --frequency Minute \
  --interval 2 \
  --start-time "$START" \
  --expiry-time "$EXPIRY" \
  --time-zone "Etc/UTC" \
  --description "Poll genie4cv Gmail every 2 min; start VM if user mail waiting." \
  2>/dev/null || az automation schedule update \
    --resource-group "$RG" \
    --automation-account-name "$AA" \
    --name "$SCHEDULE" \
    --is-enabled true

JS_ID="$(az automation job-schedule list -g "$RG" --automation-account-name "$AA" --query "[?contains(name, '$SCHEDULE')].jobScheduleId" -o tsv 2>/dev/null || true)"
if [[ -z "$JS_ID" ]]; then
  az automation job-schedule create \
    --resource-group "$RG" \
    --automation-account-name "$AA" \
    --runbook-name "$RUNBOOK" \
    --schedule-name "$SCHEDULE"
fi

CONN_URL="$(az deployment group show -g "$RG" -n logic-app-email-wake --query properties.outputs.gmailConnectionPortalUrl.value -o tsv 2>/dev/null || true)"
if [[ -z "$CONN_URL" ]]; then
  CONN_URL="https://portal.azure.com/#resource/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG}/providers/Microsoft.Web/connections/gmail-genie4cv"
fi

cat <<EOF

Done.

1) Logic App: la-email-wake-home-agents
   - Gmail trigger polls every 3 min (Azure cloud, VM can be off)
   - ONE-TIME OAuth required for genie4cv@gmail.com:
     $CONN_URL
     Open → Edit API connection → Authorize → sign in as genie4cv@gmail.com

2) Automation fallback: runbook $RUNBOOK every 2 min (uses Gmail app password, no OAuth)
   - Already uses Automation managed identity to start the VM

After Gmail OAuth, send a test email to genie4cv@gmail.com with VM stopped — VM should start within ~3 min.
EOF
