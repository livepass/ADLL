# Install the AST-guard / pre-launch cleanup repair into the protected staging.
# Verifies pinned bytes only; does not create accounts, change production ACLs,
# or run the account probe.
#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$Stage
)
$ErrorActionPreference = 'Stop'
$env:PSModulePath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\Modules;$env:ProgramFiles\WindowsPowerShell\Modules"
if (Get-LocalUser | Where-Object Name -eq 'ADLLTest') { throw 'ADLLTest exists; do not update staging during an active experiment.' }

# New bytes (candidate) and the exact prior bytes expected in staging.
$expected = @{
    'scripts/create_adll_probe_account.ps1' = '6D9E6830FAE78931420628F5252D22DC1CE5673DAEFDA94D635D4BA068E3ECE7'
    'manifest.json' = '364568C7ECEECD912AC267AED9CEC968612C9670EF4796B52CA31E419FE2D017'
}
$prior = @{
    'scripts/create_adll_probe_account.ps1' = 'B8E4263EACD2A646C6B9E753FE1DFC9BF7AFF3517F44A668CA240F0BC85801B3'
}
$priorManifestHash = 'C75781D28CAF11D639AD18AFA4BF4E7B9BB318BA8B9ACE2880FF20EE95F6F80D'

# Known obsolete file left in staging by an earlier install; hash-pinned, never
# executed, removed only when the bytes match exactly.
$obsolete = @{
    'install_account_staging_repair.ps1' = 'D169D239CAA384C9EC0B39E92AEA54A7740D7AA70BF8096D6BCD92B8333B168F'
}

function Get-BytesHash([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-', '') }
    finally { $sha.Dispose() }
}

function Assert-NoReparse([string]$Root) {
    $item = Get-Item -LiteralPath $Root -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse root: $Root" }
    foreach ($child in @(Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop)) {
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse item: $($child.FullName)" }
    }
}

function Assert-StageAcl([string]$Root) {
    $items = @((Get-Item -LiteralPath $Root -Force)) + @(Get-ChildItem -LiteralPath $Root -Recurse -Force)
    foreach ($item in $items) {
        $acl = Get-Acl -LiteralPath $item.FullName -ErrorAction Stop
        $usersRead = $false
        $adminFull = @{}
        foreach ($rule in $acl.Access) {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($rule.AccessControlType -eq 'Allow') {
                if ($sid -in @('S-1-5-18', 'S-1-5-32-544')) {
                    if (([int]$rule.FileSystemRights -band 0x1F01FF) -eq 0x1F01FF) { $adminFull[$sid] = $true }
                }
                if ($sid -notin @('S-1-5-18', 'S-1-5-32-544')) {
                    $readMask = [int][Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [int][Security.AccessControl.FileSystemRights]::Synchronize
                    if (([int]$rule.FileSystemRights -band (-bnot $readMask)) -ne 0) {
                        throw "Non-admin write permission: $($item.FullName) $sid"
                    }
                }
                if ($sid -eq 'S-1-5-32-545' -and
                    (([int]$rule.FileSystemRights -band 131241) -eq 131241)) { $usersRead = $true }
            }
        }
        if (-not $adminFull.ContainsKey('S-1-5-18') -or -not $adminFull.ContainsKey('S-1-5-32-544')) {
            throw "SYSTEM/Administrators FullControl missing: $($item.FullName)"
        }
        if (-not $usersRead) { throw "Users ReadAndExecute missing: $($item.FullName)" }
    }
}

$Stage = [IO.Path]::GetFullPath($Stage).TrimEnd('\')
$Candidate = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
$requiredStage = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'ADLL-Account-Staging'
if ($Stage -ine $requiredStage) { throw 'Unexpected staging destination' }
if (-not (Test-Path -LiteralPath $Candidate)) { throw "Candidate not found: $Candidate" }
if (-not (Test-Path -LiteralPath $Stage)) { throw "Stage not found: $Stage" }
Assert-NoReparse $Candidate
Assert-NoReparse $Stage

# The running staging must still be the exact prior version.
$installedManifestPath = Join-Path $Stage 'manifest.json'
if (-not (Test-Path -LiteralPath $installedManifestPath)) { throw 'Missing installed manifest' }
if ((Get-FileHash -LiteralPath $installedManifestPath -Algorithm SHA256).Hash -ne $priorManifestHash) {
    throw 'Installed manifest is not the expected prior version'
}
$installed = Get-Content -LiteralPath $installedManifestPath -Raw -ErrorAction Stop | ConvertFrom-Json
foreach ($entry in $installed.files.PSObject.Properties) {
    if ($expected.ContainsKey($entry.Name)) { continue }
    $actual = (Get-FileHash -LiteralPath (Join-Path $Stage $entry.Name) -Algorithm SHA256).Hash
    if ($actual -ne $entry.Value) { throw "Installed unchanged file mismatch: $($entry.Name)" }
}
foreach ($name in $prior.Keys) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $Stage $name) -Algorithm SHA256).Hash
    if ($actual -ne $prior[$name]) { throw "Installed prior version mismatch: $name" }
}

# Read and pin every candidate byte before writing anything.
$payload = @{}
foreach ($name in $expected.Keys) {
    $bytes = [IO.File]::ReadAllBytes((Join-Path $Candidate $name))
    if ((Get-BytesHash $bytes) -ne $expected[$name]) { throw "Candidate digest mismatch: $name" }
    $payload[$name] = $bytes
}
$manifest = [Text.Encoding]::UTF8.GetString($payload['manifest.json']) | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    if ($expected.ContainsKey($entry.Name)) { continue }
    if ((Get-FileHash -LiteralPath (Join-Path $Stage $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
        throw "Staged dependency mismatch: $($entry.Name)"
    }
}
foreach ($entry in $manifest.external) {
    if ((Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash -ne $entry.sha256) {
        throw "External runtime mismatch: $($entry.path)"
    }
}

# Write exactly the bytes that passed the pinned checks; manifest last.
$names = @($expected.Keys | Where-Object { $_ -ne 'manifest.json' } | Sort-Object)
foreach ($name in ($names + @('manifest.json'))) {
    [IO.File]::WriteAllBytes((Join-Path $Stage $name), $payload[$name])
    if ((Get-FileHash -LiteralPath (Join-Path $Stage $name) -Algorithm SHA256).Hash -ne $expected[$name]) {
        throw "Installed digest mismatch: $name"
    }
}

# The new manifest must now describe every staged file.
foreach ($entry in $manifest.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $Stage $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
        throw "Post-install digest mismatch: $($entry.Name)"
    }
}

# Remove the pinned obsolete installer; refuse to touch anything else.
foreach ($name in $obsolete.Keys) {
    $path = Join-Path $Stage $name
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $obsolete[$name]) { throw "Obsolete file hash mismatch: $name" }
    Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    Write-Output "Removed obsolete staged file: $name"
}

# Staging must contain only manifest-listed files (no unverified payloads).
$allowed = @($manifest.files.PSObject.Properties | ForEach-Object { $_.Name }) + @('manifest.json')
foreach ($file in @(Get-ChildItem -LiteralPath $Stage -Recurse -File -Force -ErrorAction Stop)) {
    $relative = $file.FullName.Substring($Stage.Length + 1).Replace('\', '/')
    if ($relative -notin $allowed) { throw "Unverified staged file present: $relative" }
}

Assert-StageAcl $Stage
Write-Output 'STAGING_AST_INSTALLED; account probe NOT RUN'
Write-Output ("script_sha256=" + $expected['scripts/create_adll_probe_account.ps1'])
Write-Output ("manifest_sha256=" + $expected['manifest.json'])
