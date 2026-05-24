<#
.SYNOPSIS
  Cloud-side one-time/follow-up: when gmail-genie4cv OAuth is done, enable la-email-wake-home-agents.
  Runs on Azure Automation (no Mac, no VM). Disable the linked schedule after success.
#>
param(
    [string]$ResourceGroup = "rg-home-agents",
    [string]$ConnectionName = "gmail-genie4cv",
    [string]$LogicAppName = "la-email-wake-home-agents"
)

$ErrorActionPreference = "Stop"

function Get-MsiToken {
    $meta = "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F"
    return (Invoke-RestMethod -Uri $meta -Headers @{ Metadata = "true" }).access_token
}

function Get-ConnectionStatus {
    param([string]$Token, [string]$Sub, [string]$Rg, [string]$Name)
    $uri = "https://management.azure.com/subscriptions/$Sub/resourceGroups/$Rg/providers/Microsoft.Web/connections/${Name}?api-version=2016-06-01"
    $conn = Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $Token" }
    return [string]$conn.properties.statuses[0].status
}

function Get-LogicAppState {
    param([string]$Token, [string]$Sub, [string]$Rg, [string]$Name)
    $uri = "https://management.azure.com/subscriptions/$Sub/resourceGroups/$Rg/providers/Microsoft.Logic/workflows/${Name}?api-version=2019-05-01"
    try {
        $la = Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $Token" }
        return [string]$la.properties.state
    } catch {
        return "Missing"
    }
}

function Enable-LogicApp {
    param([string]$Token, [string]$Sub, [string]$Rg, [string]$Name)
    $uri = "https://management.azure.com/subscriptions/$Sub/resourceGroups/$Rg/providers/Microsoft.Logic/workflows/${Name}?api-version=2019-05-01"
    $body = @{ properties = @{ state = "Enabled" } } | ConvertTo-Json -Depth 3
    Invoke-RestMethod -Method PATCH -Uri $uri -Headers @{ Authorization = "Bearer $Token" } -Body $body -ContentType "application/json" | Out-Null
}

$token = Get-MsiToken
$sub = (Invoke-RestMethod -Uri "http://169.254.169.254/metadata/instance/compute/subscriptionId?api-version=2021-02-01&format=text" -Headers @{ Metadata = "true" }).Trim()

$connStatus = Get-ConnectionStatus -Token $token -Sub $sub -Rg $ResourceGroup -Name $ConnectionName
Write-Output "Gmail connection status: $connStatus"
if ($connStatus -ne "Connected") {
    Write-Output "Waiting for Gmail OAuth in Azure Portal (connection $ConnectionName)."
    exit 0
}

$laState = Get-LogicAppState -Token $token -Sub $sub -Rg $ResourceGroup -Name $LogicAppName
Write-Output "Logic App state: $laState"
if ($laState -eq "Enabled") {
    Write-Output "Logic App already enabled."
    exit 0
}

if ($laState -eq "Missing") {
    Write-Output "Logic App resource not deployed yet. Run deploy.sh once from a machine with az login, or deploy ARM template logic-app-email-wake.json."
    exit 0
}

Enable-LogicApp -Token $token -Sub $sub -Rg $ResourceGroup -Name $LogicAppName
Write-Output "Enabled Logic App $LogicAppName."
