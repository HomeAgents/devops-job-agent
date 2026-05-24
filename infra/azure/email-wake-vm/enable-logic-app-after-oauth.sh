#!/usr/bin/env bash
# After Gmail OAuth: deploy Logic App workflow and enable it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RG="${AZURE_RG:-rg-home-agents}"

echo "Deploying Logic App workflow (requires authorized gmail-genie4cv connection)..."
if ! az deployment group create \
  --resource-group "$RG" \
  --name logic-app-email-wake-enabled \
  --template-file "$ROOT/logic-app-email-wake.json" \
  --parameters subscriptionId="$(az account show --query id -o tsv)" \
  --output table; then
  echo ""
  echo "If deployment failed with GmailConnectorPolicyViolation, authorize Gmail first:"
  TENANT=$(az account show --query tenantId -o tsv)
  OID=$(az ad signed-in-user show --query id -o tsv)
  az rest --method post \
    --uri "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Web/connections/gmail-genie4cv/listConsentLinks?api-version=2016-06-01" \
    --body "{\"parameters\":[{\"parameterName\":\"token\",\"redirectUrl\":\"https://portal.azure.com/\",\"objectId\":\"$OID\",\"tenantId\":\"$TENANT\"}]}" \
    --query "value[0].link" -o tsv
  exit 1
fi

az logic workflow update -g "$RG" -n la-email-wake-home-agents --state Enabled -o none
echo "Logic App la-email-wake-home-agents is Enabled."
