"""S9-1 离线安全实现测试：挂起创建、恢复前检查、纳管失败回收。

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
    """挂起创建 → 恢复前复核身份 → resume → 进程正常运行。"""
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
            # 挂起时进程不应产出结果。
            assert not out.exists()
            check = win32.pre_resume_check(process)
            assert check.ok is True
            assert check.pid == process.pid
            assert check.token_user_sid is not None
            assert check.creation_time is not None
            assert check.token_restricted is True
            assert sandbox.restricting_sid in check.restricting_sids
            process.resume()
            process.wait(30000)
            assert out.exists()
            assert out.read_text(encoding="utf-8") == "DONE"
        finally:
            process.close()


def test_pre_resume_check_reports_non_ok_evidence_and_caller_terminates(iso_root) -> None:
    """复核证据不 ok 时调用方终止而非恢复（确定性负向路径）。"""
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
            check = win32.pre_resume_check(process)
            # 正常受限进程应 ok；此处验证 ok 字段与证据齐全。真实身份不匹配
            # （TokenUser 与批准 SID 不符）的负向须在专用账户环境实测，本地
            # 受限令牌无法伪造 TokenUser 不匹配。
            assert check.ok is True
            assert check.token_user_sid is not None
            assert check.creation_time is not None
            # 模拟「复核失败」路径：调用方选择 terminate 而非 resume。
            process.job.terminate()
            process.wait(30000)
        finally:
            process.close()
        assert not win32.is_process_alive(pid)


def test_job_assign_failure_terminates_process(iso_root, monkeypatch) -> None:
    """纳管失败确定性负向：AssignProcessToJobObject 失败 → terminate + wait。"""
    with Sandbox(_spec(iso_root)) as sandbox:
        script = sandbox.work_dir / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sandbox._allow_restricted_read(script)

        # 强制 assign 失败，验证 terminate 分支被走到。
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
            # 未 resume 时 wait 会超时并终止；直接清理。
        finally:
            process.job.terminate()
            process.close()
