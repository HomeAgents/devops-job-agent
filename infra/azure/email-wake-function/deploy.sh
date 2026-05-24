#!/usr/bin/env bash
# Deploy func-email-wake-home-agents (timer + IMAP → start vm-home-agents).
# Requires: az login, func CLI (optional), SSH to VM for Gmail app password.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FUNC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG="${AZURE_RG:-rg-home-agents}"
LOC="${AZURE_LOCATION:-}"
if [[ -z "$LOC" ]]; then
  LOC="$(az group show -g "$RG" --query location -o tsv 2>/dev/null || echo westeurope)"
fi
# Consumption Functions are not available in all regions (e.g. israelcentral).
if [[ "$LOC" == "israelcentral" ]]; then
  LOC="westeurope"
fi
FA="${AZURE_FUNCTION_APP:-func-email-wake-home-agents}"
VM_NAME="${AZURE_VM_NAME:-vm-home-agents}"
LA_START="${LA_START:-la-start-home-agents-vm}"
VM_SSH="${VM_SSH:-azureuser@20.217.203.43}"

SUB="$(az account show --query id -o tsv)"
SCOPE="/subscriptions/$SUB/resourceGroups/$RG"

echo "==> Subscription $SUB  RG $RG  Function $FA"

ST="${FA//-/}st"
ST="${ST:0:24}"
if ! az storage account show -g "$RG" -n "$ST" &>/dev/null; then
  echo "==> Storage account $ST"
  az storage account create -g "$RG" -n "$ST" -l "$LOC" --sku Standard_LRS -o none
fi

if ! az functionapp show -g "$RG" -n "$FA" &>/dev/null; then
  echo "==> Function App $FA (Consumption)"
  az functionapp create \
    -g "$RG" -n "$FA" \
    --storage-account "$ST" \
    --consumption-plan-location "$LOC" \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --os-type Linux \
    -o none
fi

echo "==> Managed identity + VM Contributor"
az functionapp identity assign -g "$RG" -n "$FA" -o none 2>/dev/null || true
PID="$(az functionapp identity show -g "$RG" -n "$FA" --query principalId -o tsv)"
az role assignment create \
  --assignee "$PID" \
  --role "Virtual Machine Contributor" \
  --scope "$SCOPE/providers/Microsoft.Compute/virtualMachines/$VM_NAME" \
  -o none 2>/dev/null || true

echo "==> Ensure la-start-home-agents-vm callback (optional fallback)"
if [[ -f "$ROOT/infra/azure/email-wake-vm/deploy-finished.sh" ]]; then
  bash "$ROOT/infra/azure/email-wake-vm/deploy-finished.sh" || true
fi
CALLBACK=""
if az logic workflow show -g "$RG" -n "$LA_START" &>/dev/null; then
  CALLBACK="$(az rest --method post \
    --uri "$SCOPE/providers/Microsoft.Logic/workflows/$LA_START/triggers/manual/listCallbackUrl?api-version=2019-05-01" \
    --query value -o tsv 2>/dev/null || true)"
fi

echo "==> Gmail app password"
APP_PASS="${GMAIL_APP_PASSWORD:-}"
if [[ -z "$APP_PASS" ]]; then
  APP_PASS="$(ssh -o ConnectTimeout=15 "$VM_SSH" "grep '^EMAIL_PASS=' ~/apps/devops-job-agent/.env 2>/dev/null | cut -d= -f2-" || true)"
fi
if [[ -z "$APP_PASS" ]]; then
  echo "ERROR: Set GMAIL_APP_PASSWORD or ensure VM .env has EMAIL_PASS." >&2
  exit 1
fi

GMAIL_USER="${GMAIL_EMAIL:-genie4cv@gmail.com}"

echo "==> App settings"
az functionapp config appsettings set -g "$RG" -n "$FA" --settings \
  "GMAIL_EMAIL=$GMAIL_USER" \
  "GMAIL_APP_PASSWORD=$APP_PASS" \
  "ORCHESTRATOR_SMTP_USER=$GMAIL_USER" \
  "AZURE_SUBSCRIPTION_ID=$SUB" \
  "AZURE_VM_RG=$RG" \
  "AZURE_VM_NAME=$VM_NAME" \
  "WAKE_LOGIC_APP_URL=$CALLBACK" \
  -o none

echo "==> Build deployment package"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp "$FUNC_DIR/function_app.py" "$FUNC_DIR/host.json" "$FUNC_DIR/requirements.txt" "$STAGING/"
mkdir -p "$STAGING/orchestrator"
for f in __init__.py wake_poll.py email_filters.py email_client.py; do
  cp "$ROOT/orchestrator/$f" "$STAGING/orchestrator/"
done
(
  cd "$STAGING"
  zip -qr deploy.zip .
)

echo "==> Publish zip"
az functionapp deployment source config-zip -g "$RG" -n "$FA" --src "$STAGING/deploy.zip" -o none

echo "==> Enable Function"
az functionapp function show -g "$RG" -n "$FA" --function-name email_wake -o none 2>/dev/null || true

echo ""
echo "Done. Function $FA polls Gmail every 2 minutes and starts $VM_NAME when actionable UNSEEN mail exists."
echo "  Portal: https://portal.azure.com/#resource$SCOPE/providers/Microsoft.Web/sites/$FA"
echo ""
echo "On VM set ORCHESTRATOR_VM_AUTOSTOP=1 so poll-inbox stops VM after 15 min idle."
