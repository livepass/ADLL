"""Offline evidence regression tests; no accounts, ACLs or probes executed."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('account_selfcheck', ROOT / 'scripts/account_selfcheck.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize('encoding', ['gbk', 'ascii', 'utf-8'])
def test_json_output_roundtrips_unencodable_characters(monkeypatch, encoding):
    evidence = {'error': '\ufffd 中文 😀', 'ok': False}
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding=encoding, errors='strict')
    monkeypatch.setattr(MODULE.sys, 'stdout', stream)
    MODULE.write_evidence(evidence, None)
    stream.flush()
    output = buffer.getvalue()
    assert output.isascii()
    assert json.loads(output.decode('utf-8')) == evidence


def test_file_evidence_roundtrip(tmp_path):
    path = tmp_path / 'evidence.json'
    evidence = {'error': '\ufffd 中文 😀', 'ok': False}
    MODULE.write_evidence(evidence, path)
    assert json.loads(path.read_text(encoding='utf-8')) == evidence


def test_failed_self_check_leaves_later_stages_not_run(tmp_path, monkeypatch):
    from app.agents import worker
    monkeypatch.setenv('ProgramData', str(tmp_path))
    monkeypatch.setattr(MODULE.sys, 'argv', ['probe', '--base', str(tmp_path / 'ADLL-Account-SelfCheck'),
        '--project-root', str(tmp_path), '--out', str(tmp_path / 'result.json')])
    monkeypatch.setattr(MODULE, 'current_sid', lambda: 'S-1-5-21-test')
    monkeypatch.setattr(MODULE, 'group_names', lambda: ['S-1-5-32-545'])
    monkeypatch.setattr(MODULE, 'deny', lambda *a: 'D:')
    monkeypatch.setattr(MODULE, 'restore', lambda *a, **k: None)
    class Adapter:
        def __init__(self, **kwargs): pass
        def self_check(self): return SimpleNamespace(ok=False, details={'error': 'synthetic'})
        def generate(self, *args): pytest.fail('generation must not run after failed boundary check')
    monkeypatch.setattr(worker, 'WorkerAgentAdapter', Adapter)
    monkeypatch.setattr(MODULE, 'job_check', lambda *a: pytest.fail('job should not run'))
    assert MODULE.main() == 3
    evidence = json.loads((tmp_path / 'result.json').read_text(encoding='utf-8'))
    assert evidence['self_check']['status'] == 'failed'
    assert evidence['generate']['status'] == evidence['job']['status'] == 'not_run'
    assert evidence['generate']['ok'] is None


@pytest.mark.parametrize('code', [0, 7])
def test_real_child_exit_code_with_retained_handle(tmp_path, code):
    # Current-user child only: no credential, account, ACL, or network operation.
    harness = tmp_path / 'exit.ps1'
    harness.write_text('''param($Source, [int]$Code)
$ErrorActionPreference='Stop'
$env:PSModulePath="$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\Modules;$env:ProgramFiles\\WindowsPowerShell\\Modules"
$t=$null; $e=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$handle=$ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$processHandle'},$true)
$capture=$ast.Find({param($n) $n -is [System.Management.Automation.Language.TryStatementAst] -and $n.Body.Extent.Text.Trim() -eq '{ $probeExitCode = $proc.ExitCode }'},$true)
if ($null -eq $handle -or $null -eq $capture) { throw 'required isolated AST fragment missing' }
$proc=Start-Process -FilePath "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -ArgumentList @('-NoProfile','-NonInteractive','-Command',"Start-Sleep -Milliseconds 100; exit $Code") -WindowStyle Hidden -PassThru
. ([scriptblock]::Create($handle.Extent.Text))
if (-not $proc.WaitForExit(10000)) { throw 'test child timed out' }
$probeExitCode=$null
. ([scriptblock]::Create($capture.Extent.Text))
if ($null -eq $probeExitCode) { throw 'exit code unavailable' }
$probeExitCode
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness),
        str(ROOT / 'scripts/create_adll_probe_account.ps1'), str(code)], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(code).encode()


@pytest.mark.parametrize('evidence,verified,exit_code,expected', [
    (None, False, 1, False),
    ({}, True, 0, False),
    ({'checks': {}}, True, 0, False),
    ({'checks': {'project_read': {'ok': True}}}, True, 0, False),
    ({'checks': {'project_read': {'ok': False, 'error': 'FileNotFoundError'}}}, True, 0, False),
    ({'checks': {'project_read': {'ok': False, 'error': 'PermissionError'}}}, False, 0, False),
    ({'checks': {'project_read': {'ok': False, 'error': 'PermissionError'}}}, True, 3, False),
    ({'checks': {'project_read': {'ok': 'false', 'error': 'PermissionError'}}}, True, 0, False),
    ({'checks': {'project_read': {'ok': False, 'error': 'PermissionError'}}}, True, 0, True),
])
def test_production_isolation_requires_verified_denial(tmp_path, evidence, verified, exit_code, expected):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(evidence), encoding='utf-8')
    # Extract ONLY the pure predicate via AST; never dot-source the account script.
    harness = tmp_path / 'predicate.ps1'
    harness.write_text('''param($Source, $InputPath, [int]$Verified, [int]$Code)
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'parse failure' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-ProductionIsolation'},$true)
if ($null -eq $fn) { throw 'missing predicate' }
. ([scriptblock]::Create($fn.Extent.Text))
$evidence=Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
Test-ProductionIsolation $evidence ([bool]$Verified) $Code
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness),
                             str(ROOT / 'scripts/create_adll_probe_account.ps1'), str(path),
                             str(int(verified)), str(exit_code)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (b'True' if expected else b'False')


def test_parent_reads_stdout_as_utf8():
    source = (ROOT / 'scripts/create_adll_probe_account.ps1').read_text(encoding='utf-8-sig')
    assert '[IO.File]::ReadAllText($stdout, [Text.Encoding]::UTF8)' in source
    assert 'production_isolation_pass = (Test-ProductionIsolation $parsed ($verifyErrors.Count -eq 0) $probeExitCode)' in source


@pytest.mark.parametrize('raw', ['', '{invalid', json.dumps({
    'ok': False, 'error': 'AdapterDisabled', 'group_sids': ['S-1-5-32-545'],
    'self_check': {'details': {'evidence': {'details': {'diagnostic': {
        'exception_type': 'PrivilegeNotHeldException', 'hresult': -2147024891,
        'phase': 'persist_acl', 'privilege_name': None}}}}},
    'cleanup_errors': [{'type': 'AclOperationError'}, 'rmtree:PermissionError'],
    'checks': {'project_read': {'ok': True}}, 'text': '中文\ufffd😀'
}, ensure_ascii=False)])
def test_complete_record_serialization_uses_plain_raw_string(tmp_path, raw):
    stdout = tmp_path / 'stdout.json'
    stdout.write_text(raw, encoding='utf-8')
    harness = tmp_path / 'record.ps1'
    harness.write_text('''param($Source, $stdout, $OutputPath)
$ErrorActionPreference='Stop'
$env:PSModulePath="$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\Modules;$env:ProgramFiles\\WindowsPowerShell\\Modules"
$t=$null; $e=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if ($e.Count) { throw 'parse error' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-ProductionIsolation'},$true)
. ([scriptblock]::Create($fn.Extent.Text))
$read=$ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$raw'},$true)
. ([scriptblock]::Create($read.Extent.Text))
if ($raw.PSObject.Properties.Name -contains 'PSDrive') { throw 'provider metadata on raw text' }
$parsed=$null
try { $parsed=$raw | ConvertFrom-Json } catch { $parsed=$null }
$nonce='test'; $proc=[pscustomobject]@{ExitCode=3}; $probeExitCode=3
$sha=(Get-FileHash -LiteralPath $stdout).Hash
$scriptHashBefore=$sha; $scriptHashAfter=$sha
$verifyErrors=New-Object System.Collections.Generic.List[string]
$verifyErrors.Add('selfcheck_not_ok')
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$record'},$true)
. ([scriptblock]::Create($node.Extent.Text))
$json=$record | ConvertTo-Json -Depth 30
[IO.File]::WriteAllText($OutputPath,$json,[Text.Encoding]::UTF8)
''', encoding='utf-8-sig')
    output = tmp_path / 'record.json'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness),
        str(ROOT / 'scripts/create_adll_probe_account.ps1'), str(stdout), str(output)],
        capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(output.read_text(encoding='utf-8-sig'))
    assert isinstance(evidence['evidence_raw'], str)
    assert evidence['evidence_raw'] == raw
    assert evidence['verified'] is False
    assert evidence['production_isolation_pass'] is False
    assert evidence['verification_errors'] == ['selfcheck_not_ok']
    if raw.startswith('{"'):
        assert evidence['parsed'] == json.loads(raw)


def test_phase_log_is_persistent_and_does_not_include_credentials(tmp_path):
    harness = tmp_path / 'phase.ps1'
    harness.write_text('''param($Source, $Parent)
$ErrorActionPreference='Stop'
$t=$null; $e=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if ($e.Count) { throw 'parse error' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-ProbePhase'},$true)
. ([scriptblock]::Create($fn.Extent.Text))
$nonce='test-nonce'; $secure='MUST-NOT-LOG'; $cred='MUST-NOT-LOG'
$probeClock=[Diagnostics.Stopwatch]::StartNew()
Write-ProbePhase 'before_start_process'
Write-ProbePhase 'start_process_returned'
$commands=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true))
$before=@($commands | Where-Object { $_.Extent.Text -eq "Write-ProbePhase 'before_start_process'" })[0]
$start=@($commands | Where-Object { $_.GetCommandName() -eq 'Start-Process' })[0]
$after=@($commands | Where-Object { $_.Extent.Text -eq "Write-ProbePhase 'start_process_returned'" })[0]
if (-not ($before.Extent.StartOffset -lt $start.Extent.StartOffset -and $start.Extent.EndOffset -lt $after.Extent.StartOffset)) { throw 'incorrect phase ordering' }
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness),
                             str(ROOT / 'scripts/create_adll_probe_account.ps1'), str(tmp_path)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    text = (tmp_path / 'launch-phases.jsonl').read_text(encoding='utf-8-sig')
    records = [json.loads(line) for line in text.splitlines()]
    assert [r['phase'] for r in records] == ['before_start_process', 'start_process_returned']
    assert all(set(r) == {'utc', 'phase', 'parent_pid', 'nonce', 'elapsed_ms'} for r in records)
    assert 'MUST-NOT-LOG' not in text


@pytest.mark.parametrize('exited', [True, False])
def test_bounded_wait_records_timeout_without_cleanup(tmp_path, exited):
    harness = tmp_path / 'wait.ps1'
    harness.write_text('''param($Source, $Parent, [int]$Exited)
$ErrorActionPreference='Stop'
$t=$null; $e=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if ($e.Count) { throw 'parse error' }
$launch=$ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Extent.Text -eq '$launchAttempted = $true'},$true)
$start=$ast.Find({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Start-Process'},$true)
if ($null -eq $launch -or $launch.Extent.StartOffset -ge $start.Extent.StartOffset) { throw 'unsafe launch ordering' }
if (@($start.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Wait' }).Count) { throw 'unbounded wait' }
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Clauses[0].Item1.Extent.Text -like '*WaitForExit*'},$true)
$proc=[pscustomobject]@{Id=123; Exited=[bool]$Exited}
$proc | Add-Member ScriptMethod WaitForExit { param($ms) if ($ms -ne 1000) { throw 'wrong timeout' }; return $this.Exited }
$ProbeTimeoutSeconds=1; $nonce='test'
try { . ([scriptblock]::Create($node.Extent.Text)); 'COMPLETED' }
catch { if ($_.Exception.Message -notlike 'Probe wait timed out*') { throw }; 'TIMEOUT' }
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(harness),
                             str(ROOT / 'scripts/create_adll_probe_account.ps1'), str(tmp_path),
                             str(int(exited))], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    record = tmp_path / 'wait-failure.json'
    if exited:
        assert b'COMPLETED' in result.stdout
        assert not record.exists()
    else:
        assert b'TIMEOUT' in result.stdout
        evidence = json.loads(record.read_text(encoding='utf-8-sig'))
        assert evidence['verified'] is False
        assert evidence['account_retained'] is True
