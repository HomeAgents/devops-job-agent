#!/usr/bin/env bash
# VM-side helper: publish + schedule cloud runbook that enables Logic App after Gmail OAuth.
# No az login on VM required — runs on Azure Automation account aa-home-agents.
set -euo pipefail
ROOT="${HOME}/apps/devops-job-agent"
SRC="$ROOT/infra/azure/email-wake-vm/Enable-EmailWakeLogicApp.ps1"
RG="${AZURE_RG:-rg-home-agents}"
AA="${AZURE_AUTOMATION_ACCOUNT:-aa-home-agents}"
RUNBOOK="Enable-EmailWakeLogicApp"
SCHEDULE="sched-enable-email-wake-logic-app"

if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC — git pull devops-job-agent first." >&2
  exit 1
fi

echo "This script registers a cloud runbook on Azure Automation ($AA)."
echo "After you authorize Gmail in Azure Portal, Automation enables the Logic App automatically."
echo ""
echo "Portal: https://portal.azure.com/#resource/subscriptions/40f9da3f-642b-4815-9af4-4556e9114038/resourceGroups/rg-home-agents/providers/Microsoft.Web/connections/gmail-genie4cv/overview"
echo ""
echo "Note: initial Logic App ARM deploy still needs az login once (Mac or Cloud Shell):"
echo "  cd infra/azure/email-wake-vm && ./deploy.sh"
echo ""
echo "If deploy.sh already ran, you only need Gmail OAuth in the portal — nothing on Mac/VM."
