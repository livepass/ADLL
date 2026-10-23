# ADLL batch 10: temporary account isolation check.
# Run manually in administrator Windows PowerShell; enter password locally.
# Only dedicated temporary directories under ProgramData may have ACL changes.
#Requires -RunAsAdministrator
param(
    [string]$PythonExe = 'D:\wo\python\Python312\python.exe',
    [string]$ProjectRoot = 'D:\wo\code\ADLL\ADLL',
    [ValidateRange(1,3600)][int]$ProbeTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
# Load cmdlets only from protected system module directories.
$env:PSModulePath = 'C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules'
$Stage = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $Stage 'app'
$SelfCheck = Join-Path $PSScriptRoot 'account_selfcheck.py'
$Python = $PythonExe
$Manifest = Join-Path $Stage 'manifest.json'
$Name = 'ADLLTest'
$Base = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'ADLL-Account-SelfCheck'
$Parent = Join-Path $Base 'parent'
$Work = Join-Path $Base 'work'

function Write-ProbePhase([string]$Phase) {
    [pscustomobject]@{
        utc = [DateTime]::UtcNow.ToString('o')
        phase = $Phase
        parent_pid = $PID
        nonce = $nonce
        elapsed_ms = $probeClock.ElapsedMilliseconds
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $Parent 'launch-phases.jsonl') -Encoding UTF8
    Write-Host "Probe phase: $Phase"
}

function Test-ProductionIsolation($Evidence, [bool]$Verified, [int]$ExitCode) {
    if (-not $Verified -or $ExitCode -ne 0 -or $null -eq $Evidence) { return $false }
    $read = $Evidence.checks.project_read
    return ($null -ne $read -and $read.ok -is [bool] -and
        $read.ok -eq $false -and $read.error -ceq 'PermissionError')
}

function Test-StagingManifest {
    if (-not (Test-Path -LiteralPath $Manifest)) { throw "Missing staging manifest: $Manifest" }
    $data = Get-Content -LiteralPath $Manifest -Raw -ErrorAction Stop | ConvertFrom-Json
    foreach ($entry in $data.files.PSObject.Properties) {
        $path = Join-Path $Stage $entry.Name
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing staged file: $path" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $entry.Value) { throw "Staging hash mismatch: $path" }
    }
    foreach ($entry in @($data.external)) {
        if (-not (Test-Path -LiteralPath $entry.path)) { throw "Missing external file: $($entry.path)" }
        $actual = (Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash
        if ($actual -ne $entry.sha256) { throw "External hash mismatch: $($entry.path)" }
    }
    if (-not (@($data.external | Where-Object { $_.path -ieq $Python }))) {
        throw "PythonExe is not covered by the staging manifest: $Python"
    }
}

function Assert-NotReparse([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing reparse point: $Path"
        }
    }
}

function Assert-NoReparseDescendants([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $bad = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($bad.Count -gt 0) {
        throw "Refusing cleanup: reparse points present directly under $Path"
    }
}

function Get-AclForPath([string]$Path, [string]$Label) {
    # Single standalone statement: a malformed comment line cannot absorb it.
    # Any failure is converted into an explicit, path-bearing exception.
    $acl = $null
    try {
        $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    } catch {
        throw "Unable to read $Label ACL at ${Path}: $($_.Exception.GetType().Name): $($_.Exception.Message)"
    }
    if ($null -eq $acl) { throw "Get-Acl returned null for $Label at ${Path}" }
    if ($null -eq $acl.Access) { throw "ACL for $Label at ${Path} has no access rules" }
    return $acl
}

function Remove-EmptyDirectory([string]$Path) {
    # Only removes a directory that exists and is empty; never touches evidence.
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $children = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)
    if ($children.Count -gt 0) { return $false }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    return $true
}

function Set-AdminOnly([string]$Path) {
    $acl = Get-AclForPath -Path $Path -Label 'admin-only target'
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRule($rule) }
    $system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $admins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    foreach ($sid in @($system, $admins)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    # The restricted token performs a second (restricting-SID) access check.
    # Users is one of its restricting SIDs; Traverse-only keeps the test base
    # unreadable/unlistable while allowing the probe to reach its own sandbox.
    $users = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-545')
    $traverse = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $users, 'Traverse, ReadAttributes, Synchronize', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($traverse)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if (Get-LocalUser -Name $Name -ErrorAction SilentlyContinue) {
    throw "Account $Name already exists; refusing to modify/overwrite/delete it."
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path -LiteralPath $SelfCheck)) { throw "Self-check not found: $SelfCheck" }
if (-not (Test-Path -LiteralPath $AppRoot)) { throw "Staged app not found: $AppRoot" }
if (-not (Test-Path -LiteralPath $ProjectRoot)) { throw "Project root not found: $ProjectRoot" }
Test-StagingManifest
Assert-NotReparse $Base
if (Test-Path -LiteralPath $Base) {
    # A previous pre-launch failure can leave only empty parent/work directories.
    # Remove those (never non-empty ones) so the next experiment starts clean.
    foreach ($staleDir in @($Parent, $Work)) {
        try {
            if (Remove-EmptyDirectory -Path $staleDir) {
                Write-Output "Removed stale empty directory: $staleDir"
            }
        } catch {
            Write-Output "WARNING: stale empty directory cleanup failed: $($_.Exception.Message)"
        }
    }
    $existing = @(Get-ChildItem -LiteralPath $Base -Force -ErrorAction Stop)
    if ($existing.Count -gt 0) {
        # Preserve prior evidence instead of overwriting or refusing to run.
        $archive = '{0}-{1}' -f $Base, [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
        if (Test-Path -LiteralPath $archive) {
            throw "Refusing: archive target already exists: $archive"
        }
        Move-Item -LiteralPath $Base -Destination $archive -ErrorAction Stop
        Write-Output "Archived previous experiment directory: $archive"
        New-Item -ItemType Directory -Force -Path $Base | Out-Null
        Assert-NotReparse $Base
    }
}

$secure = Read-Host -AsSecureString "Enter a temporary password for $Name (input is hidden)"
if ($secure.Length -eq 0) { throw "Empty password is not allowed." }

$created = $false
$probeStarted = $false
$launchAttempted = $false
$user = $null
try {
    $user = New-LocalUser -Name $Name -Password $secure -AccountNeverExpires `
        -PasswordNeverExpires -Description 'ADLL temporary isolation test account'
    $created = $true
    $sid = $user.SID.Value
    $adminMember = @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "$env:COMPUTERNAME\$Name" })
    if ($adminMember.Count -gt 0) {
        throw "Refusing: $Name unexpectedly belongs to Administrators."
    }
    $usersMember = @(Get-LocalGroupMember -SID 'S-1-5-32-545' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "$env:COMPUTERNAME\$Name" })
    if ($usersMember.Count -eq 0) {
        Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $user
    }
    Write-Output "Created $Name ($sid); Administrators=false; Users=true"

    New-Item -ItemType Directory -Force -Path $Base | Out-Null
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    New-Item -ItemType Directory -Force -Path $Work | Out-Null
    Assert-NotReparse $Base
    Assert-NotReparse $Parent
    Assert-NotReparse $Work
    Set-AdminOnly $Base
    Set-AdminOnly $Parent
    Set-AdminOnly $Work

    # Grant Base traversal only; grant Modify on Work separately.
    $baseAcl = Get-AclForPath -Path $Base -Label 'Base'
    $traverseRule = New-Object System.Security.AccessControl.FileSystemAccessRule($user.SID, 'ReadAndExecute', 'None', 'None', 'Allow')
    $baseAcl.AddAccessRule($traverseRule)
    Set-Acl -LiteralPath $Base -AclObject $baseAcl

    # Keep Parent evidence admin-only; grant account Modify only on Work.
    $workAcl = Get-AclForPath -Path $Work -Label 'Work'
    $workRule = New-Object System.Security.AccessControl.FileSystemAccessRule($user.SID, 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $workAcl.AddAccessRule($workRule)
    Set-Acl -LiteralPath $Work -AclObject $workAcl

    $nonce = [guid]::NewGuid().ToString('N')
    $stdout = Join-Path $Parent 'selfcheck.stdout.json'
    $stderr = Join-Path $Parent 'selfcheck.stderr.txt'
    $scriptHashBefore = (Get-FileHash -LiteralPath $SelfCheck -Algorithm SHA256).Hash
    $appHashBefore = (Get-ChildItem -LiteralPath $AppRoot -Recurse -File -Filter '*.py' |
        Sort-Object FullName | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join ''
    $cred = New-Object System.Management.Automation.PSCredential("$env:COMPUTERNAME\$Name", $secure)
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $savedPath = $env:PATH
    $savedPythonPath = $env:PYTHONPATH
    $savedPythonHome = $env:PYTHONHOME
    $env:PATH = 'C:\Windows\System32;C:\Windows'
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    try {
        $probeClock = [Diagnostics.Stopwatch]::StartNew()
        Write-ProbePhase 'before_start_process'
        $launchAttempted = $true
        $proc = Start-Process -FilePath $Python `
            -ArgumentList @('-I', '-S', $SelfCheck, '--base', $Work, '--out', '-', '--nonce', $nonce, '--project-root', $ProjectRoot) `
            -Credential $cred -WorkingDirectory $Stage -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        Write-ProbePhase 'start_process_returned'
        $probeStarted = $true
        # Retain the native handle before the child exits (Windows PowerShell 5.1).
        $processHandle = $proc.Handle
        Write-ProbePhase 'process_handle_retained'
        Write-ProbePhase 'before_wait_for_exit'
        if (-not $proc.WaitForExit($ProbeTimeoutSeconds * 1000)) {
            [pscustomobject]@{
                verified = $false
                production_isolation_pass = $false
                verification_errors = @('probe_wait_timeout')
                process_id = $proc.Id
                nonce = $nonce
                account_retained = $true
            } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Parent 'wait-failure.json') -Encoding UTF8
            throw 'Probe wait timed out; account and processes retained for manual inspection.'
        }
        Write-ProbePhase 'wait_for_exit_returned'
        $probeExitCode = $null
        try { $probeExitCode = $proc.ExitCode } catch { }
        Write-ProbePhase 'exit_code_captured'
    } finally {
        $env:PATH = $savedPath
        if ($null -ne $savedPythonPath) { $env:PYTHONPATH = $savedPythonPath }
        if ($null -ne $savedPythonHome) { $env:PYTHONHOME = $savedPythonHome }
    }
    $probeStarted = $true
    $scriptHashAfter = (Get-FileHash -LiteralPath $SelfCheck -Algorithm SHA256).Hash
    $appHashAfter = (Get-ChildItem -LiteralPath $AppRoot -Recurse -File -Filter '*.py' |
        Sort-Object FullName | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join ''

    Write-ProbePhase 'before_read_evidence'
    $raw = if (Test-Path -LiteralPath $stdout) { [IO.File]::ReadAllText($stdout, [Text.Encoding]::UTF8) } else { '' }
    $parsed = $null
    try { $parsed = $raw | ConvertFrom-Json } catch { $parsed = $null }
    $sha = if (Test-Path -LiteralPath $stdout) {
        (Get-FileHash -LiteralPath $stdout -Algorithm SHA256).Hash
    } else { '' }
    $verifyErrors = New-Object System.Collections.Generic.List[string]
    if ($scriptHashBefore -ne $scriptHashAfter) { $verifyErrors.Add('selfcheck_script_modified') }
    if ($appHashBefore -ne $appHashAfter) { $verifyErrors.Add('app_source_modified') }
    if ($null -eq $parsed) { $verifyErrors.Add('evidence_not_json') }
    elseif ($parsed.nonce -ne $nonce) { $verifyErrors.Add('nonce_mismatch') }
    if ($parsed -and $parsed.sid -ne $sid) { $verifyErrors.Add('sid_mismatch') }
    if ($parsed -and $parsed.ok -ne $true) { $verifyErrors.Add('selfcheck_not_ok') }
    if ($parsed -and (@($parsed.group_sids).Count -eq 0 -or @($parsed.group_sids) -contains 'S-1-5-32-544')) {
        $verifyErrors.Add('admin_group_present')
    }
    if ($null -eq $probeExitCode) { $verifyErrors.Add('exit_code_unavailable') }
    elseif ($probeExitCode -ne 0) { $verifyErrors.Add('exit_code_nonzero') }
    if ($parsed -and ($null -eq $parsed.self_check -or $parsed.self_check.status -eq 'not_run')) { $verifyErrors.Add('self_check_not_run') }
    elseif ($parsed -and $parsed.self_check.ok -ne $true) { $verifyErrors.Add('self_check_failed') }
    if ($parsed -and ($null -eq $parsed.generate -or $parsed.generate.status -eq 'not_run')) { $verifyErrors.Add('generate_not_run') }
    elseif ($parsed -and $parsed.generate.ok -ne $true) { $verifyErrors.Add('generate_failed') }
    if ($parsed -and ($null -eq $parsed.job -or $parsed.job.status -eq 'not_run')) { $verifyErrors.Add('job_not_run') }
    elseif ($parsed -and $parsed.job.ok -ne $true) { $verifyErrors.Add('job_failed') }
    foreach ($key in @('account_read_allowed','account_repo_denied','account_db_denied',
                       'account_user_denied','account_db_write_denied')) {
        if ($parsed -and $parsed.checks.$key.ok -ne $true) {
            $verifyErrors.Add("check_failed:$key")
        }
    }
    if ($parsed -and @($parsed.cleanup_errors).Count -gt 0) {
        $verifyErrors.Add('cleanup_errors')
    }
    $projectReadable = $false
    if ($parsed -and $parsed.checks.project_read.ok -eq $true) {
        $projectReadable = $true
    }

    $record = [pscustomobject]@{
        nonce = $nonce
        verified = ($verifyErrors.Count -eq 0)
        verification_errors = @($verifyErrors)
        exit_code = $probeExitCode
        selfcheck_sha256 = $sha
        selfcheck_script_sha256_before = $scriptHashBefore
        selfcheck_script_sha256_after = $scriptHashAfter
        production_isolation_pass = (Test-ProductionIsolation $parsed ($verifyErrors.Count -eq 0) $probeExitCode)
        parsed = $parsed
        evidence_raw = $raw
    }
    Write-ProbePhase 'before_serialize_evidence'
    $record | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $Parent 'evidence.json') -Encoding utf8
    Write-ProbePhase 'evidence_written'
    Write-Output "Self-check exit code: $probeExitCode"
    Write-Output "Evidence (admin-only): $(Join-Path $Parent 'evidence.json')"
    Write-Output "Verification errors: $($verifyErrors -join ', ')"
    if ($projectReadable) {
        Write-Output "PRODUCTION S10/S14: FAIL (ADLLTest can read project directory)"
    }

    $live = @()
    $liveCheckFailed = $false
    try {
        $live = @(Get-Process -IncludeUserName -ErrorAction Stop |
            Where-Object { $_.UserName -like "*\$Name" })
    } catch {
        $liveCheckFailed = $true
        Write-Output "WARNING: cannot enumerate processes; account NOT deleted."
    }
    if ($liveCheckFailed -or $live.Count -gt 0) {
        if ($live.Count -gt 0) {
            Write-Output "WARNING: live processes remain for ${Name}: $($live.Id -join ', '); account NOT deleted."
        }
    } else {
        $answer = Read-Host "Delete temporary account $Name now? Type yes to delete"
        if ($answer -eq 'yes') {
            Remove-LocalUser -Name $Name
            $profile = Get-CimInstance Win32_UserProfile -ErrorAction SilentlyContinue |
                Where-Object { $_.SID -eq $sid }
            if ($profile -and -not $profile.Loaded) {
                try { Remove-CimInstance -InputObject $profile -ErrorAction Stop }
                catch { Write-Output "WARNING: profile cleanup failed: $($_.Exception.Message)" }
            }
            try {
                Assert-NoReparseDescendants $Work
                $remaining = @(Get-ChildItem -LiteralPath $Work -Force -ErrorAction Stop)
                if ($remaining.Count -eq 0) {
                    Remove-Item -LiteralPath $Work -Force -ErrorAction Stop
                } else {
                    Write-Output "Work directory not empty; retained for manual inspection: $Work"
                }
            }
            catch { Write-Output "WARNING: work directory cleanup failed: $($_.Exception.Message)" }
            Write-Output "Deleted $Name. Evidence retained at $(Join-Path $Parent 'evidence.json')"
        } else {
            Write-Output "Account retained by user choice; delete it after verification."
        }
    }
} catch {
    if ($created -and $user -and -not $launchAttempted) {
        try { Remove-LocalUser -Name $Name -ErrorAction Stop } catch {
            Write-Output "WARNING: automatic account cleanup failed: $($_.Exception.Message)"
        }
    } elseif ($launchAttempted) {
        Write-Output "Probe launch attempted; account retained for investigation/cleanup. Error: $($_.Exception.Message)"
    }
    if (-not $launchAttempted -and (Test-Path -LiteralPath $Work)) {
        try {
            Assert-NoReparseDescendants $Work
            if (Remove-EmptyDirectory -Path $Work) {
                Write-Output "Removed empty work directory: $Work"
            } else {
                Write-Output "Work directory not empty; retained: $Work"
            }
        }
        catch { Write-Output "WARNING: work directory cleanup failed: $($_.Exception.Message)" }
    }
    if (-not $launchAttempted) {
        # Remove only directories that ended up empty; any evidence is retained.
        foreach ($emptyDir in @($Parent, $Base)) {
            try {
                if (Remove-EmptyDirectory -Path $emptyDir) {
                    Write-Output "Removed empty experiment directory: $emptyDir"
                }
            } catch {
                Write-Output "WARNING: empty directory cleanup failed: $($_.Exception.Message)"
            }
        }
    }
    throw
}