#!/usr/bin/env bash
# Disable Azure automations that wake/run home agents VM.
set -euo pipefail
RG="${RG:-rg-home-agents}"
VM="${VM:-vm-home-agents}"

for wf in la-morning-wake-home-agents la-start-home-agents-vm logic-autoheal-agents; do
  az logic workflow show -g "$RG" -n "$wf" >/dev/null 2>&1 && \
    az logic workflow update -g "$RG" -n "$wf" --set state=Disabled -o none && \
    echo "Disabled Logic App: $wf" || true
done

for app in func-email-wake-home-agents funcemailwakehomeagentss; do
  az functionapp show -g "$RG" -n "$app" >/dev/null 2>&1 && \
    az functionapp stop -g "$RG" -n "$app" -o none && \
    echo "Stopped Function App: $app" || true
done

az vm deallocate -g "$RG" -n "$VM" -o none || true
az vm get-instance-view -g "$RG" -n "$VM" --query "instanceView.statuses[?starts_with(code,'PowerState/')].displayStatus" -o tsv
