# Ventra SFTP deployment script (Phase 4 hybrid — dev environment).
#
# Purpose: stand up the two SFTP endpoints (stdspec + preagg) in the dev
# resource group so you can test end-to-end before Ventra's first real
# drop. This script does NOT touch prod.
#
# What it does:
#   1. Generates two SSH keypairs (one per local user) — TEST keys only.
#   2. Updates infra/env/dev.bicepparam in-place to flip the SFTP toggles on.
#   3. Runs az deployment what-if (preview) — you review the resource diff.
#   4. Runs az deployment group create (apply).
#   5. Prints the SFTP connection info Ventra will use.
#
# When Ventra goes live, the TEST keys get replaced by Ventra's real public
# keys (we keep their private keys NEVER — they stay on Ventra's side).
# Re-run the deployment with the new keys + the dev.bicepparam already
# flipped on.
#
# Requires:
#   - az CLI logged in to the hhamedicine.com tenant
#   - ssh-keygen on PATH (ships with Git for Windows / OpenSSH for Windows)
#   - The dev RG exists (rg-hha-dashboard-dev)

param(
    [string]$ResourceGroup = "rg-hha-dashboard-dev",
    [string]$KeyDir = "$env:USERPROFILE\.ssh\ventra-test",
    # -ImportKeys <dir>: copy Ventra's real public keys (ventra-stdspec.pub +
    # ventra-preagg.pub) from <dir> into $KeyDir and skip keygen. Use this
    # once Ventra has sent their public keys (they keep the private keys and
    # connect TO our SFTP). Pass the repo's committed copy:
    #   -ImportKeys "<repo>\docs\06-vendors\ventra\sftp-keys"
    # or the raw download folder.
    [string]$ImportKeys = "",
    [switch]$WhatIfOnly,
    [switch]$SkipKeygen
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host ""
Write-Host "=============================================="
Write-Host " Ventra SFTP deploy — Phase 4 hybrid (dev)"
Write-Host "=============================================="
Write-Host ""
Write-Host "Repo root:      $RepoRoot"
Write-Host "Resource group: $ResourceGroup"
Write-Host "Key directory:  $KeyDir"
Write-Host ""

# Step 0 — confirm Azure login is fresh
Write-Host "[0/4] Confirming Azure login..."
try {
    $sub = az account show --query "{name:name, state:state, user:user.name}" -o json 2>$null | ConvertFrom-Json
    if ($sub.state -ne "Enabled") {
        throw "Subscription is not Enabled — re-run 'az login' and retry."
    }
    Write-Host "      Logged in as $($sub.user) on $($sub.name)"
} catch {
    Write-Host "      Not logged in. Run:" -ForegroundColor Yellow
    Write-Host "        az login --tenant 76596b76-3c41-40ee-a8a3-bf6930301838"
    exit 1
}

# Quick sanity — verify the RG exists. This is the call that fails first if
# the management-API token is expired (the symptom seen on 2026-06-03).
try {
    az group show -n $ResourceGroup --query "name" -o tsv 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "RG not found" }
} catch {
    Write-Host "      Could not read resource group '$ResourceGroup'." -ForegroundColor Yellow
    Write-Host "      Either the RG doesn't exist OR your token has expired." -ForegroundColor Yellow
    Write-Host "      Re-login: az logout; az login --tenant 76596b76-3c41-40ee-a8a3-bf6930301838"
    exit 1
}

# Step 1 — import Ventra's real public keys, OR generate test keypairs.
#
# When Ventra has sent their public keys (-ImportKeys <dir>), we copy the
# two .pub files into $KeyDir and skip keygen entirely — HHA never needs
# the private keys; Ventra keeps those and connects TO our SFTP. Otherwise
# we generate throwaway test keypairs so the endpoints can be smoke-tested
# locally before Ventra is wired in.
if ($ImportKeys -ne "") {
    Write-Host ""
    Write-Host "[1/4] Importing Ventra public keys from $ImportKeys ..."
    if (-not (Test-Path $KeyDir)) {
        New-Item -ItemType Directory -Path $KeyDir -Force | Out-Null
    }
    foreach ($name in @("ventra-stdspec.pub", "ventra-preagg.pub")) {
        $src = Join-Path $ImportKeys $name
        if (-not (Test-Path $src)) {
            Write-Host "      Missing $src" -ForegroundColor Red
            Write-Host "      Expected ventra-stdspec.pub + ventra-preagg.pub in the import dir."
            exit 1
        }
        Copy-Item $src (Join-Path $KeyDir $name) -Force
        Write-Host "      Imported $name"
    }
    $SkipKeygen = $true
}

if (-not $SkipKeygen) {
    Write-Host ""
    Write-Host "[1/4] Generating test SSH keypairs..."
    if (-not (Test-Path $KeyDir)) {
        New-Item -ItemType Directory -Path $KeyDir -Force | Out-Null
    }
    $stdspecKey = Join-Path $KeyDir "ventra-stdspec"
    $preaggKey  = Join-Path $KeyDir "ventra-preagg"

    if (-not (Test-Path $stdspecKey)) {
        ssh-keygen -t ed25519 -f $stdspecKey -N '""' -C "ventra-stdspec-dev-test" | Out-Null
        Write-Host "      Generated $stdspecKey + .pub"
    } else {
        Write-Host "      Reusing existing $stdspecKey"
    }
    if (-not (Test-Path $preaggKey)) {
        ssh-keygen -t ed25519 -f $preaggKey -N '""' -C "ventra-preagg-dev-test" | Out-Null
        Write-Host "      Generated $preaggKey + .pub"
    } else {
        Write-Host "      Reusing existing $preaggKey"
    }
} else {
    Write-Host "[1/4] Skipping keygen (--SkipKeygen)"
    $stdspecKey = Join-Path $KeyDir "ventra-stdspec"
    $preaggKey  = Join-Path $KeyDir "ventra-preagg"
}

$stdspecPub = Get-Content "$stdspecKey.pub" -Raw
$preaggPub  = Get-Content "$preaggKey.pub"  -Raw

# Step 2 — what-if preview
Write-Host ""
Write-Host "[2/4] Running az deployment what-if (preview)..."
$mainBicep = Join-Path $RepoRoot "infra\main.bicep"
$bicepparam = Join-Path $RepoRoot "infra\env\dev.bicepparam"

$workstationIp = (Invoke-WebRequest -UseBasicParsing -Uri "https://api.ipify.org" -TimeoutSec 5).Content
Write-Host "      Workstation IP for ACL: $workstationIp"

$dbPassword = -join ((33..126) | Get-Random -Count 24 | ForEach-Object {[char]$_})

$paramOverrides = @(
    "postgres_admin_password=$dbPassword",
    "deployer_workstation_ip=$workstationIp",
    "enable_vendor_storage=true",
    "enable_sftp=true",
    "enable_ventra_stdspec=true",
    "ventra_stdspec_sftp_public_key=$stdspecPub",
    "enable_ventra_preagg=true",
    "ventra_preagg_sftp_public_key=$preaggPub"
)

$paramArgs = @()
foreach ($p in $paramOverrides) { $paramArgs += "-p"; $paramArgs += $p }

Write-Host "      Reviewing changes..."
az deployment group what-if -g $ResourceGroup -f $mainBicep -p $bicepparam @paramArgs

if ($WhatIfOnly) {
    Write-Host ""
    Write-Host "[done] What-if complete; --WhatIfOnly was set so no apply."
    exit 0
}

Write-Host ""
$confirm = Read-Host "Apply this deployment? [y/N]"
if ($confirm -ne "y") {
    Write-Host "Aborted."
    exit 0
}

# Step 3 — apply
Write-Host ""
Write-Host "[3/4] Applying deployment (~3-5 minutes)..."
$deployResult = az deployment group create -g $ResourceGroup -f $mainBicep -p $bicepparam @paramArgs --query "properties.outputs" -o json
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed." -ForegroundColor Red
    exit 1
}

# Step 4 — print connection info
Write-Host ""
Write-Host "[4/4] Deployment succeeded!"
Write-Host ""
Write-Host "=============================================="
Write-Host " SFTP CONNECTION INFO"
Write-Host "=============================================="
$outputs = $deployResult | ConvertFrom-Json
if ($outputs.vendor_storage_account_name) {
    $storageAccount = $outputs.vendor_storage_account_name.value
    $sftpHost = "$storageAccount.blob.core.windows.net"

    Write-Host ""
    Write-Host "SFTP host:   $sftpHost (port 22)"
    Write-Host ""
    Write-Host "Standard Spec user (PHI-bearing path):"
    Write-Host "  username: $storageAccount.ventra-stdspec"
    Write-Host "  path:     /vendor-inbound/ventra/stdspec/YYYY-MM-DD/"
    Write-Host "  test cmd: sftp -i $stdspecKey $storageAccount.ventra-stdspec@$sftpHost"
    Write-Host ""
    Write-Host "Pre-aggregated user (no-PHI path):"
    Write-Host "  username: $storageAccount.ventra-preagg"
    Write-Host "  path:     /vendor-inbound/ventra/preagg/YYYY-MM-DD/"
    Write-Host "  test cmd: sftp -i $preaggKey $storageAccount.ventra-preagg@$sftpHost"
} else {
    Write-Host "Storage account name was not returned in outputs — check the deploy log."
}
Write-Host ""
Write-Host "Private keys (DO NOT share):"
Write-Host "  $stdspecKey"
Write-Host "  $preaggKey"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Test the connection: sftp -i <private-key> <user>@<host>"
Write-Host "  2. Once Ventra provides their REAL public keys, re-run this"
Write-Host "     script with --SkipKeygen and replace the .pub files first."
Write-Host "  3. Share ONLY the host + username (path) with Ventra — never"
Write-Host "     share any private key file."
