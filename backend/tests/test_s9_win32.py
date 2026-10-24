"""S9-1 离线安全实现测试：挂起创建、恢复前强制身份检查、纳管失败回收。

仅 Windows 运行（依赖真实受限令牌 + Job Object，但不依赖独立账户/VM）。
真实 LogonUserW / 独立 TokenUser / VM 网络权限不在此判定，须在实际专用环境另行验收。
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.isolation import win32
from app.isolation.sandbox import IsolationSpec, Sandbox, default_python

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows-only restricted process"),
]

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def iso_root():
    root = Path(tempfile.mkdtemp(prefix=f"adll-s91-{uuid.uuid4().hex[:8]}-", dir=BACKEND))
    try:
        yield root
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _spec(root: Path) -> IsolationSpec:
    return IsolationSpec(sandbox_root=root, acl_root=root, process_timeout_seconds=30)


def test_suspended_spawn_and_pre_resume_check_then_resume(iso_root) -> None:
    """挂起创建 → 恢复前强制复核（批准 SID + restricting SID + Job）→ resume → 运行。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "echo.py"
        out = sandbox.work_dir / "done.txt"
        script.write_text(
            f"open({str(out)!r}, 'w', encoding='utf-8').write('DONE')\n",
            encoding="utf-8",
        )
        sandbox._allow_restricted_read(script)
        process = win32.spawn_restricted(
            [default_python(), "-I", str(script)],
            cwd=sandbox.work_dir,
            env=win32.build_environment(),
            restricting_sid=sandbox.restricting_sid,
            stdout_path=sandbox.work_dir / "s_out.txt",
            stderr_path=sandbox.work_dir / "s_err.txt",
            suspended=True,
        )
        try:
            assert not out.exists()
            # 批准的 TokenUser SID 即父进程当前用户 SID（本地受限令牌复用父令牌主体）。
            check = win32.pre_resume_check(
                process,
                expected_token_user_sid=sandbox.parent_sid,
                expected_restricting_sid=sandbox.restricting_sid,
            )
            assert check.ok is True, check.fail_reasons
            assert check.pid == process.pid
            assert check.token_user_sid == sandbox.parent_sid
            assert check.in_job is True
            assert sandbox.restricting_sid in check.restricting_sids
            process.resume()
            process.wait(30000)
            assert out.exists()
            assert out.read_text(encoding="utf-8") == "DONE"
        finally:
            process.close()


def test_pre_resume_check_rejects_wrong_restricting_sid(iso_root) -> None:
    """确定性负向：期望 restricting SID 与实际不符 → ok=False，须 terminate。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sandbox._allow_restricted_read(script)
        process = win32.spawn_restricted(
            [default_python(), "-I", str(script)],
            cwd=sandbox.work_dir,
            env=win32.build_environment(),
            restricting_sid=sandbox.restricting_sid,
            suspended=True,
        )
        pid = process.pid
        try:
            check = win32.pre_resume_check(
                process,
                expected_token_user_sid=sandbox.parent_sid,
                expected_restricting_sid="S-1-5-21-9999999999-9999999999-9999999999-9999",
            )
            assert check.ok is False
            assert "restricting_sid_mismatch" in check.fail_reasons
            # 未通过检查 → 直接 resume 应被拒绝。
            with pytest.raises(RuntimeError):
                process.resume()
            # 调用方必须 terminate + wait 而非只关闭句柄。
            process.job.terminate()
            process.wait(30000)
        finally:
            process.close()
        assert not win32.is_process_alive(pid)


def test_resume_denied_without_passing_check(iso_root) -> None:
    """确定性负向：未经检查通过，resume 必须拒绝（不静默放行）。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sandbox._allow_restricted_read(script)
        process = win32.spawn_restricted(
            [default_python(), "-I", str(script)],
            cwd=sandbox.work_dir,
            env=win32.build_environment(),
            restricting_sid=sandbox.restricting_sid,
            suspended=True,
        )
        try:
            with pytest.raises(RuntimeError):
                process.resume()
        finally:
            process.job.terminate()
            process.close()


def test_pre_resume_check_rejects_wrong_token_user(iso_root) -> None:
    """确定性负向：期望 TokenUser SID 与实际不符 → ok=False。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sandbox._allow_restricted_read(script)
        process = win32.spawn_restricted(
            [default_python(), "-I", str(script)],
            cwd=sandbox.work_dir,
            env=win32.build_environment(),
            restricting_sid=sandbox.restricting_sid,
            suspended=True,
        )
        try:
            check = win32.pre_resume_check(
                process,
                expected_token_user_sid="S-1-5-21-8888888888-8888888888-8888888888-8888",
                expected_restricting_sid=sandbox.restricting_sid,
            )
            assert check.ok is False
            assert "token_user_mismatch" in check.fail_reasons
        finally:
            process.job.terminate()
            process.close()


def test_job_assign_failure_terminates_process(iso_root, monkeypatch) -> None:
    """纳管失败确定性负向：AssignProcessToJobObject 失败 → terminate + wait。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sandbox._allow_restricted_read(script)

        def fake_assign(self, handle):
            raise OSError("simulated assign failure")

        monkeypatch.setattr(win32.JobObject, "assign", fake_assign)
        with pytest.raises(OSError):
            win32.spawn_restricted(
                [default_python(), "-I", str(script)],
                cwd=sandbox.work_dir,
                env=win32.build_environment(),
                restricting_sid=sandbox.restricting_sid,
            )


def test_suspended_spawn_requires_explicit_resume(iso_root) -> None:
    """挂起创建后未 resume 的进程不运行（确定性负向：无隐式恢复）。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "mark.py"
        marker = sandbox.work_dir / "ran.txt"
        script.write_text(
            f"open({str(marker)!r}, 'w').write('RAN')\n", encoding="utf-8"
        )
        sandbox._allow_restricted_read(script)
        process = win32.spawn_restricted(
            [default_python(), "-I", str(script)],
            cwd=sandbox.work_dir,
            env=win32.build_environment(),
            restricting_sid=sandbox.restricting_sid,
            suspended=True,
        )
        try:
            import time

            time.sleep(0.5)
            assert not marker.exists()
        finally:
            process.job.terminate()
            process.close()
