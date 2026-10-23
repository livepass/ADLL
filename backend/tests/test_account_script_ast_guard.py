"""Static guards for scripts/create_adll_probe_account.ps1.

Windows PowerShell 5.1 only. The account script is parsed, never executed:
no account is created, no ACL is touched, no probe is launched.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / 'scripts/create_adll_probe_account.ps1'
CHECKER = Path(__file__).with_name('check_account_script_ast_guard.ps1')
INSTALLER = BACKEND / 'scripts/install_account_staging_ast.ps1'
CANDIDATE = BACKEND / 'staging-account-ast-20261023'
STAGING_MANIFEST = Path(r'C:\ProgramData\ADLL-Account-Staging\manifest.json')

BASE_ASSIGN = "$baseAcl = Get-AclForPath -Path $Base -Label 'Base'"
WORK_ASSIGN = "$workAcl = Get-AclForPath -Path $Work -Label 'Work'"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashtable_literal(text: str, name: str) -> dict:
    match = re.search(rf'\${name}\s*=\s*@\{{(.*?)\n\}}', text, re.DOTALL)
    assert match, f'missing ${name} literal'
    return {
        key: value.upper()
        for key, value in re.findall(r"'([^']+)'\s*=\s*'([0-9A-Fa-f]{64})'", match.group(1))
    }


def string_literal(text: str, name: str) -> str:
    match = re.search(rf'\${name}\s*=\s*\'([0-9A-Fa-f]{{64}})\'', text)
    assert match, f'missing ${name} literal'
    return match.group(1).upper()


def parse_with_ast(path: Path) -> subprocess.CompletedProcess:
    """Run the PowerShell AST checker; -ExecutionPolicy Bypass is parse-only."""
    return subprocess.run(
        [
            'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(CHECKER), '-Path', str(path),
        ],
        capture_output=True, timeout=60, check=False,
    )


def test_script_is_utf8_bom_and_ascii_only():
    """BOM plus ASCII keeps PS 5.1 from guessing a legacy code page."""
    data = SCRIPT.read_bytes()
    assert data.startswith(b'\xef\xbb\xbf')
    text = data.decode('utf-8-sig')
    assert text.isascii()
    assert '\\u' not in text


def test_ast_confirms_real_script_executes_acl_assignments():
    result = parse_with_ast(SCRIPT)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
    assert b'ACL_AST_OK' in result.stdout


@pytest.mark.parametrize(
    ('statement', 'variable'),
    [(BASE_ASSIGN, 'baseAcl'), (WORK_ASSIGN, 'workAcl')],
)
def test_ast_rejects_assignment_swallowed_by_comment(tmp_path, statement, variable):
    """Reproduce the reported defect: '#' absorbs the Get-Acl assignment."""
    text = SCRIPT.read_text(encoding='utf-8-sig')
    assert text.count(statement) == 1
    broken = text.replace(statement, f'# swallowed {statement}', 1)
    path = tmp_path / 'broken.ps1'
    path.write_text(broken, encoding='utf-8-sig')
    result = parse_with_ast(path)
    assert result.returncode != 0
    assert f'Missing or duplicate executable assignment: {variable}'.encode() in result.stderr


def test_ast_rejects_comment_that_contains_code(tmp_path):
    text = SCRIPT.read_text(encoding='utf-8-sig')
    broken = text + "\n# $baseAcl = Get-Acl -LiteralPath $Base\n"
    path = tmp_path / 'broken.ps1'
    path.write_text(broken, encoding='utf-8-sig')
    result = parse_with_ast(path)
    assert result.returncode != 0
    assert b'Comment contains executable-looking code' in result.stderr


def test_ast_rejects_nonterminating_acl_read(tmp_path):
    text = SCRIPT.read_text(encoding='utf-8-sig')
    broken = text.replace(
        'Get-Acl -LiteralPath $Path -ErrorAction Stop',
        'Get-Acl -LiteralPath $Path',
        1,
    )
    assert broken != text
    path = tmp_path / 'broken.ps1'
    path.write_text(broken, encoding='utf-8-sig')
    result = parse_with_ast(path)
    assert result.returncode != 0
    assert b'-ErrorAction Stop' in result.stderr


def test_ast_rejects_missing_null_guard(tmp_path):
    text = SCRIPT.read_text(encoding='utf-8-sig')
    guard = 'if ($null -eq $acl) { throw "Get-Acl returned null for $Label at ${Path}" }'
    assert guard in text
    broken = text.replace(guard, '# removed null guard', 1)
    path = tmp_path / 'broken.ps1'
    path.write_text(broken, encoding='utf-8-sig')
    result = parse_with_ast(path)
    assert result.returncode != 0
    assert b'must reject a null ACL' in result.stderr


def test_ast_rejects_missing_set_acl(tmp_path):
    text = SCRIPT.read_text(encoding='utf-8-sig')
    target = 'Set-Acl -LiteralPath $Base -AclObject $baseAcl'
    broken = text.replace(target, '# removed Set-Acl', 1)
    path = tmp_path / 'broken.ps1'
    path.write_text(broken, encoding='utf-8-sig')
    result = parse_with_ast(path)
    assert result.returncode != 0
    assert b'Missing Set-Acl' in result.stderr


def test_installer_parses_under_windows_powershell_51():
    command = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{INSTALLER}',[ref]$null,[ref]$e); "
        "if ($e.Count) { $e | Out-String; exit 1 } else { 'PARSE_OK' }"
    )
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-Command', command],
        capture_output=True, timeout=60, check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
    assert b'PARSE_OK' in result.stdout


def test_candidate_staging_matches_its_manifest():
    manifest = json.loads((CANDIDATE / 'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        assert sha256(CANDIDATE / name) == digest.lower(), name
    assert manifest['files']['scripts/create_adll_probe_account.ps1'] == sha256(SCRIPT).lower()


def test_installer_pins_the_candidate_bytes():
    text = INSTALLER.read_text(encoding='utf-8')
    expected = hashtable_literal(text, 'expected')
    assert expected['scripts/create_adll_probe_account.ps1'] == sha256(SCRIPT).upper()
    assert expected['manifest.json'] == sha256(CANDIDATE / 'manifest.json').upper()


def test_installer_pins_match_the_installed_staging_state():
    """Staging must be either the exact prior version or the exact new one.

    The installer is one-shot: before it runs, staging equals `prior`; after it
    runs, staging equals `expected`. Anything else means a stale pin.
    """
    if not STAGING_MANIFEST.is_file():
        pytest.skip('staging is not installed on this host')
    text = INSTALLER.read_text(encoding='utf-8')
    expected = hashtable_literal(text, 'expected')
    installed_manifest = sha256(STAGING_MANIFEST).upper()
    installed = json.loads(STAGING_MANIFEST.read_text(encoding='utf-8-sig'))

    if installed_manifest == expected['manifest.json']:
        for name, digest in expected.items():
            if name == 'manifest.json':
                continue
            assert installed['files'][name].upper() == digest, name
        return

    assert installed_manifest == string_literal(text, 'priorManifestHash')
    for name, digest in hashtable_literal(text, 'prior').items():
        assert installed['files'][name].upper() == digest, name
