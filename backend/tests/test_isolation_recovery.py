"""Offline fault injection; never changes real ACLs or starts account processes."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.isolation import sandbox as sb
from app.isolation import win32

BACKEND = Path(__file__).resolve().parents[1]


def _load_selfcheck_module():
    spec = importlib.util.spec_from_file_location(
        "adll_account_selfcheck", BACKEND / "scripts" / "account_selfcheck.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeProcess:
    token_restricted = True
    restricting_sids: list[str] = []
    restricting_sid_attributes: dict[str, int] = {}

    def __init__(self, stderr_text: str = "", evidence: str | None = None) -> None:
        self.stderr_text = stderr_text
        self.evidence = evidence
        self.closed = False

    def wait(self, timeout_ms: int) -> int:
        if self.stderr_text:
            stderr_path = self.stderr_path
            stderr_path.write_text(self.stderr_text, encoding="utf-8")
        if self.evidence is not None:
            self.evidence_path.write_text(self.evidence, encoding="utf-8")
        return 1

    def close(self) -> None:
        self.closed = True


def test_powershell_failure_keeps_only_structured_diagnostics(monkeypatch):
    monkeypatch.setattr(win32.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=b'', stderr=b'{"hresult":-1,"category":"PermissionDenied","exception_type":"Test","secret":"DO-NOT-COPY"}'))
    with pytest.raises(win32.AclOperationError) as caught:
        win32._powershell('sensitive-command', 'restore_dacl')
    assert caught.value.diagnostic['operation'] == 'restore_dacl'
    assert caught.value.diagnostic['hresult'] == -1
    assert 'DO-NOT-COPY' not in str(caught.value.diagnostic)


@pytest.mark.parametrize('directory', [True, False])
def test_restore_targets_dacl_only(monkeypatch, directory):
    captured = []
    monkeypatch.setattr(win32, '_powershell', lambda *args: captured.append(args))
    monkeypatch.setattr(Path, 'is_dir', lambda self: pytest.fail('must use saved object type'))
    win32.restore_sddl(Path('synthetic'), 'D:', is_directory=directory)
    assert 'AccessControlSections]::Access' in captured[0][0]
    assert 'Get-Acl' not in captured[0][0]
    assert 'GetAccessControl' not in captured[0][0]
    assert 'Set-Acl' not in captured[0][0]
    assert ('[IO.Directory]::SetAccessControl' if directory else '[IO.File]::SetAccessControl') in captured[0][0]


@pytest.mark.parametrize('directory', [True, False])
def test_acl_rule_uses_access_only_dotnet_api(tmp_path, monkeypatch, directory):
    path = tmp_path / 'object'
    if directory:
        path.mkdir()
    else:
        path.write_text('synthetic')
    commands = []
    def capture(script, operation):
        commands.append((script, operation))
        return 'D:'
    monkeypatch.setattr(win32, '_powershell', capture)
    change = win32.allow_sid(path, 'S-1-5-32-545', tmp_path)
    assert change.is_directory is directory
    assert len(commands) == 2
    assert all('AccessControlSections]::Access' in cmd for cmd, op in commands)
    assert all('Set-Acl' not in cmd and 'Get-Acl' not in cmd for cmd, op in commands)
    assert '[IO.' + ('Directory' if directory else 'File') + ']::SetAccessControl' in commands[1][0]


def test_restore_attempts_every_entry_and_reports_failure(monkeypatch):
    seen = []
    def restore(path, value, **kwargs):
        seen.append(path.name)
        if path.name == 'b':
            raise PermissionError('private text')
    monkeypatch.setattr(win32, 'restore_sddl', restore)
    with pytest.raises(win32.AclOperationError) as caught:
        win32.restore_acl([win32.AclChange(Path('a'), 'D:'), win32.AclChange(Path('b'), 'D:')])
    assert seen == ['b', 'a']
    assert caught.value.diagnostic['failures'][0]['type'] == 'PermissionError'
    assert 'private text' not in str(caught.value.diagnostic)


@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_constructor_failure_rolls_back(tmp_path, monkeypatch, cleanup_fails):
    restored = []
    monkeypatch.setattr(sb, 'allow_sid', lambda path, *a, **k: win32.AclChange(path, 'D:'))
    def deny(*args, **kwargs):
        raise win32.AclOperationError('deny_dacl', {'hresult': -1})
    monkeypatch.setattr(sb, 'deny_sid', deny)
    def restore(changes):
        restored.extend(changes)
        if cleanup_fails:
            raise PermissionError('cleanup')
    monkeypatch.setattr(sb, 'restore_acl', restore)
    with pytest.raises(win32.AclOperationError) as caught:
        sb.Sandbox(sb.IsolationSpec(tmp_path, deny_read=(tmp_path / 'object',)))
    # one Users-Traverse on the shared acl_root, plus
    # (parent SID + OWNER RIGHTS + restricting SID) x root/subset/work
    assert len(restored) == 10
    if cleanup_fails:
        assert caught.value.diagnostic['operation'] == 'sandbox_initialize'
        assert list(tmp_path.iterdir())  # Preserve scene after failed rollback.
    else:
        assert not list(tmp_path.iterdir())


def test_successful_close_reports_delete_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, 'allow_sid', lambda path, *a, **k: win32.AclChange(path, 'D:'))
    monkeypatch.setattr(sb, 'restore_acl', lambda changes: None)
    box = sb.Sandbox(sb.IsolationSpec(tmp_path))
    def fail(*args, **kwargs):
        raise PermissionError('delete failed')
    monkeypatch.setattr(sb.shutil, 'rmtree', fail)
    with pytest.raises(PermissionError):
        box.close()
    assert not box._closed


def test_worker_preserves_safe_failure_stage(tmp_path, monkeypatch):
    from app.agents import worker
    target = tmp_path / 'protected'
    target.write_text('synthetic')
    def fail(*args, **kwargs):
        raise win32.AclOperationError('allow_dacl', {'hresult': -1})
    monkeypatch.setattr(worker, 'Sandbox', fail)
    report = worker.WorkerAgentAdapter(endpoint='unused', model='unused',
        sandbox_root=tmp_path, deny_read=(str(target),)).self_check()
    assert report.ok is False
    assert report.details['evidence']['details']['diagnostic']['operation'] == 'allow_dacl'


def test_real_powershell_reports_phase_without_exception_message():
    # Only throws in memory: no ACL mutation, account, or process launch.
    with pytest.raises(win32.AclOperationError) as caught:
        win32._powershell("$adllPhase='persist_acl'; throw 'PRIVATE-DIAGNOSTIC-TEXT'", 'test')
    assert caught.value.diagnostic['phase'] == 'persist_acl'
    assert 'PRIVATE-DIAGNOSTIC-TEXT' not in str(caught.value.diagnostic)


def test_restore_failure_identifies_read_control_requirement(monkeypatch):
    monkeypatch.setattr(
        win32.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=(
                b'{"inner_exception_type":"System.UnauthorizedAccessException",'
                b'"exception_type":"System.Management.Automation.MethodInvocationException",'
                b'"phase":"persist_acl","hresult":-2146233087}'
            ),
        ),
    )
    with pytest.raises(win32.AclOperationError) as caught:
        win32.restore_sddl(Path("synthetic"), "D:", is_directory=True)
    assert caught.value.diagnostic["hint"] == "restore_requires_read_control_and_write_dac"


def test_probe_no_evidence_keeps_stderr_and_preflight(tmp_path, monkeypatch):
    target = tmp_path / "deny.txt"
    target.write_text("synthetic", encoding="utf-8")
    box = sb.Sandbox(sb.IsolationSpec(tmp_path, acl_root=tmp_path, deny_read=(target,)))
    fake = _FakeProcess(
        stderr_text=(
            "adll_probe_phase=read_spec\n"
            "Traceback (most recent call last):\n"
            "PermissionError: [Errno 13] Permission denied: 'probe_spec.json'\n"
        )
    )
    def spawn(command, **kwargs):
        fake.stderr_path = kwargs["stderr_path"]
        fake.evidence_path = Path(command[-1])
        return fake
    monkeypatch.setattr(sb, "spawn_restricted", spawn)
    try:
        result = box.probe(box.write_subset({"a.txt": b"a"}))
        assert result.ok is False
        assert result.error == "probe_no_evidence:exit_1"
        diagnostics = result.evidence["diagnostics"]
        assert diagnostics["exit_code"] == 1
        assert diagnostics["evidence_file"] == {"exists": False, "size": None}
        assert "PermissionError" in diagnostics["stderr_tail"]
        assert "adll_probe_phase=read_spec" in diagnostics["stderr_tail"]
        assert diagnostics["preflight"]["work_dir_has_restricting_sid"] is True
        assert diagnostics["preflight"]["spec_has_restricting_sid"] is True
    finally:
        box.close()
    # The sandbox (and its internal log) is gone, but the captured evidence is not.
    assert not box.root.exists()
    assert "PermissionError" in result.evidence["diagnostics"]["stderr_tail"]


def test_probe_invalid_evidence_keeps_diagnostics(tmp_path, monkeypatch):
    target = tmp_path / "deny.txt"
    target.write_text("synthetic", encoding="utf-8")
    box = sb.Sandbox(sb.IsolationSpec(tmp_path, acl_root=tmp_path, deny_read=(target,)))
    fake = _FakeProcess(stderr_text="adll_probe_phase=write_evidence\n", evidence="{not-json")
    def spawn(command, **kwargs):
        fake.stderr_path = kwargs["stderr_path"]
        fake.evidence_path = Path(command[-1])
        return fake
    monkeypatch.setattr(sb, "spawn_restricted", spawn)
    try:
        result = box.probe(box.write_subset({"a.txt": b"a"}))
        assert result.error.startswith("probe_evidence_invalid:")
        assert result.evidence["diagnostics"]["evidence_file"]["exists"] is True
        assert result.evidence["diagnostics"]["evidence_error"] == "JSONDecodeError"
    finally:
        box.close()


def test_probe_spec_file_carries_restricting_sid(tmp_path, monkeypatch):
    box = sb.Sandbox(sb.IsolationSpec(tmp_path, acl_root=tmp_path))
    captured = {}
    fake = _FakeProcess()
    def spawn(command, **kwargs):
        captured["spec_sddl"] = win32.get_sddl(Path(command[-2]))
        fake.stderr_path = kwargs["stderr_path"]
        fake.evidence_path = Path(command[-1])
        return fake
    monkeypatch.setattr(sb, "spawn_restricted", spawn)
    try:
        box.probe([])
        assert box.restricting_sid in captured["spec_sddl"]
        assert "OW" in captured["spec_sddl"] or "S-1-3-4" in captured["spec_sddl"]
    finally:
        box.close()


def test_worker_no_result_keeps_stderr_diagnostics(tmp_path, monkeypatch):
    box = sb.Sandbox(sb.IsolationSpec(tmp_path, acl_root=tmp_path))
    fake = _FakeProcess(
        stderr_text=(
            "adll_worker_phase=read_job\n"
            "PermissionError: [Errno 13] Permission denied: 'job.json'\n"
        )
    )
    def spawn(command, **kwargs):
        fake.stderr_path = kwargs["stderr_path"]
        fake.evidence_path = Path(command[-1])
        return fake
    monkeypatch.setattr(sb, "spawn_restricted", spawn)
    try:
        result = box.run({"mode": "synthetic", "synthetic_allowed": True})
        assert result["error"] == "worker_no_result:exit_1"
        assert "PermissionError" in result["diagnostics"]["stderr_tail"]
    finally:
        box.close()


def test_account_deny_rights_parse_without_read_control():
    module = _load_selfcheck_module()
    for rights in (module.ACCOUNT_DENY_READ, module.ACCOUNT_DENY_READ_WRITE):
        assert "ReadPermissions" not in rights
        assert "ChangePermissions" not in rights
        assert "ReadData" in rights
        # PowerShell/.NET must accept every enum name; no ACL is changed.
        win32._powershell(
            f"[System.Security.AccessControl.FileSystemRights]'{rights}' | Out-Null",
            "test_rights",
        )
