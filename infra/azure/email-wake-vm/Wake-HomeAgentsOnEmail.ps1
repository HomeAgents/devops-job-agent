<#
.SYNOPSIS
  Poll genie4cv@gmail.com (IMAP) from Azure Automation. Start vm-home-agents when
  real user mail is waiting and the VM is deallocated/stopped.

  Runs in the cloud every few minutes — no VM required for this check.
#>
param(
    [string]$Mailbox = "genie4cv@gmail.com",
    [string]$ResourceGroup = "rg-home-agents",
    [string]$VmName = "vm-home-agents"
)

$ErrorActionPreference = "Stop"

function Get-AutomationSecret {
    param([string]$Name)
    $conn = Get-AutomationConnection -Name $Name -ErrorAction SilentlyContinue
    if ($conn) { return $conn.Password }
    $var = Get-AutomationVariable -Name $Name -ErrorAction SilentlyContinue
    if ($var) {
        $raw = [string]$var.Value
        if ($raw.StartsWith('"') -and $raw.EndsWith('"')) {
            $raw = $raw.Substring(1, $raw.Length - 2)
        }
        return $raw
    }
    throw "Missing Automation secret '$Name' (Automation variable)."
}

function Read-ImapGreeting {
    param($Reader)
    while ($true) {
        $line = $Reader.ReadLine()
        if ($null -eq $line) { return $null }
        if ($line.StartsWith("*")) { return $line }
    }
}

function Invoke-ImapCommand {
    param($Writer, $Reader, [string]$Command)
    $Writer.WriteLine($Command)
    $Writer.Flush()
    $lines = New-Object System.Collections.Generic.List[string]
    while ($true) {
        $line = $Reader.ReadLine()
        if ($null -eq $line) { break }
        $lines.Add($line)
        if ($line -match '^\d+ OK') { break }
        if ($line -match '^\d+ NO' -or $line -match '^\d+ BAD') {
            throw "IMAP error on '$Command': $line"
        }
    }
    return ($lines -join "`n")
}

function Test-GmailHasActionableUnseen {
    param([string]$User, [string]$AppPassword)

    $client = New-Object System.Net.Sockets.TcpClient
    $client.ReceiveTimeout = 15000
    $client.SendTimeout = 15000
    $client.Connect("imap.gmail.com", 993)
    $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false)
    $ssl.AuthenticateAsClient("imap.gmail.com")
    $reader = New-Object System.IO.StreamReader($ssl)
    $writer = New-Object System.IO.StreamWriter($ssl)
    $writer.NewLine = "`r`n"
    $writer.AutoFlush = $true

    [void](Read-ImapGreeting $reader)
    Invoke-ImapCommand $writer $reader "a1 LOGIN $User $AppPassword" | Out-Null
    Invoke-ImapCommand $writer $reader "a2 SELECT INBOX" | Out-Null
    $search = Invoke-ImapCommand $writer $reader "a3 SEARCH UNSEEN"
    $writer.WriteLine("a4 LOGOUT")
    $writer.Flush()
    $client.Close()

    if ($search -notmatch '\* SEARCH') { return $false }
    $ids = ($search -replace '(?s).*\* SEARCH\s*', '').Trim()
    if ([string]::IsNullOrWhiteSpace($ids)) { return $false }

    $client = New-Object System.Net.Sockets.TcpClient
    $client.ReceiveTimeout = 15000
    $client.SendTimeout = 15000
    $client.Connect("imap.gmail.com", 993)
    $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false)
    $ssl.AuthenticateAsClient("imap.gmail.com")
    $reader = New-Object System.IO.StreamReader($ssl)
    $writer = New-Object System.IO.StreamWriter($ssl)
    $writer.NewLine = "`r`n"
    $writer.AutoFlush = $true
    [void](Read-ImapGreeting $reader)
    Invoke-ImapCommand $writer $reader "b1 LOGIN $User $AppPassword" | Out-Null
    Invoke-ImapCommand $writer $reader "b2 SELECT INBOX" | Out-Null

    foreach ($id in ($ids -split '\s+')) {
        if ([string]::IsNullOrWhiteSpace($id)) { continue }
        $fetch = Invoke-ImapCommand $writer $reader "b3 FETCH $id (BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])"
        $blob = $fetch.ToLower()
        if ($blob -match 'mailer-daemon|postmaster|accounts\.google\.com') { continue }
        if ($blob -match 'birthday\s*copilot|\[birthday') { continue }
        if ($blob -match 'scoutsignal|\[scoutsignal\]') { continue }
        if ($blob -match 'genie4cv@gmail\.com') { continue }
        $writer.WriteLine("b4 LOGOUT")
        $writer.Flush()
        $client.Close()
        return $true
    }

    $writer.WriteLine("b4 LOGOUT")
    $writer.Flush()
    $client.Close()
    return $false
}

function Start-HomeAgentsVmIfNeeded {
    param([string]$ResourceGroup, [string]$VmName)
    $logicAppUrl = $null
    try { $logicAppUrl = Get-AutomationVariable -Name "OrchestratorWakeLogicAppUrl" -ErrorAction Stop } catch {}
    if ($logicAppUrl -and $logicAppUrl -like "https://*") {
        try {
            Invoke-RestMethod -Method POST -Uri $logicAppUrl -Body "{}" -ContentType "application/json" | Out-Null
            Write-Output "Start VM requested via Logic App."
            return
        } catch {
            Write-Output "Logic App trigger failed ($($_.Exception.Message)); falling back to ARM."
        }
    }
    $sub = (Invoke-RestMethod -Uri "http://169.254.169.254/metadata/instance/compute/subscriptionId?api-version=2021-02-01&format=text" -Headers @{ Metadata = "true" }).Trim()
    $token = (Invoke-RestMethod -Uri "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F" -Headers @{ Metadata = "true" }).access_token
    $vmUri = "https://management.azure.com/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.Compute/virtualMachines/${VmName}?`$expand=instanceView&api-version=2024-07-01"
    $vm = Invoke-RestMethod -Uri $vmUri -Headers @{ Authorization = "Bearer $token" }
    $power = ($vm.properties.instanceView.statuses | Where-Object { $_.code -like "PowerState/*" }).code
    if ($power -eq "PowerState/running") {
        Write-Output "VM already running ($VmName)."
        return
    }
    Write-Output "Starting VM $VmName (was $power)..."
    $startUri = "https://management.azure.com/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.Compute/virtualMachines/${VmName}/start?api-version=2024-07-01"
    Invoke-RestMethod -Method POST -Uri $startUri -Headers @{ Authorization = "Bearer $token" } | Out-Null
    Write-Output "Start requested for $VmName."
}

$appPassword = Get-AutomationSecret -Name "Genie4cvGmailAppPassword"
if (Test-GmailHasActionableUnseen -User $Mailbox -AppPassword $appPassword) {
    Write-Output "Actionable unseen mail detected — waking VM."
    Start-HomeAgentsVmIfNeeded -ResourceGroup $ResourceGroup -VmName $VmName
} else {
    Write-Output "No actionable unseen mail."
}
