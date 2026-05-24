#!/usr/bin/env bash
# Post-OAuth setup (run once from any machine with az login). No Mac required day-to-day.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG="${AZURE_RG:-rg-home-agents}"
LA_START="la-start-home-agents-vm"

echo "==> Gmail connection"
az rest --method get \
  --uri "/subscriptions/$(az account show -query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Web/connections/gmail-genie4cv?api-version=2016-06-01" \
  --query "properties.statuses[0].status" -o tsv

echo "==> Deploy start-VM Logic App (HTTP only — no Gmail in same workflow)"
az deployment group create -g "$RG" -n la-start-vm-final \
  --template-file "$ROOT/logic-app-start-vm-only.json" -o none 2>/dev/null || true

PID=$(az logic workflow show -g "$RG" -n "$LA_START" --query identity.principalId -o tsv)
az role assignment create --assignee "$PID" --role "Virtual Machine Contributor" \
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG" -o none 2>/dev/null || true

az logic workflow update -g "$RG" -n "$LA_START" --state Enabled -o none

CALLBACK=$(az rest --method post \
  --uri "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Logic/workflows/$LA_START/triggers/manual/listCallbackUrl?api-version=2019-05-01" \
  --query value -o tsv)

python3 -c "
import json, subprocess
body = {'properties': {'value': json.dumps('$CALLBACK'), 'description': 'Logic App wake URL', 'isEncrypted': False}}
subprocess.run(['az','rest','--method','put','--uri',
  'https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Automation/automationAccounts/aa-home-agents/variables/OrchestratorWakeLogicAppUrl?api-version=2015-10-31',
  '--body', json.dumps(body)], check=True)
"

echo ""
echo "Done."
echo "  la-start-home-agents-vm: Enabled (POST callback starts VM)"
echo "  Gmail OAuth: Connected"
echo ""
echo "Note: @gmail.com consumer accounts cannot use Gmail trigger + HTTP in ONE Logic App."
echo "Email wake while VM is off: use Azure Function (future) or keep VM running + poll-inbox cron."
echo "Callback URL stored in Automation variable OrchestratorWakeLogicAppUrl."
