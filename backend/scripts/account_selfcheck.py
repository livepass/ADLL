"""在 ADLL 实验账户（或当前用户，仅用于自测）中运行隔离验收。

本脚本由用户以实验账户执行；不包含/读取口令。默认 `--out -` 把 JSON 证据写到
stdout，由可信父进程重定向到 ADLLTest 不可写的目录；`--nonce` 由父进程生成并复核。
覆盖：
1) 账户 SID/组；
2) WorkerAgentAdapter.self_check 实际探针（受限子进程）；
3) 账户主体对明确 Deny 的合成 repo/DB/user 的读/写失败；
4) 账户主体对项目目录的访问（用于判定生产 S10/S14 是否不通过）；
5) 回环与 TEST-NET 出站检查（**仅信息性，不作为 OS allowlist PASS 证据**）；
6) Job Object 子进程终止/未逃逸。

所有 ACL 修改仅位于 --base 下的临时目录；结束后恢复 ACL 并删除。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 账户主体自测需要自行恢复 DACL，因此 Deny 掩码刻意排除 ReadPermissions
# （READ_CONTROL）与 ChangePermissions（WRITE_DAC）。FileSystemRights.Read
# 的数值包含 READ_CONTROL，若一并 Deny，SetAccessControl 在 persist_acl
# 阶段会因无法以 READ_CONTROL|WRITE_DAC 打开对象而失败。
# 生产 ACL 由管理员施加、账户无需自恢复，可继续使用 FullControl/Read。
ACCOUNT_DENY_READ = "ReadData, ReadAttributes, ReadExtendedAttributes"
ACCOUNT_DENY_READ_WRITE = (
    "ReadData, WriteData, AppendData, ReadAttributes, WriteAttributes, "
    "ReadExtendedAttributes, WriteExtendedAttributes"
)


def _ps(script: str) -> str:
    from app.isolation.win32 import _powershell
    return _powershell(script, "account_acl_or_identity")


def _assert_not_reparse(path: Path) -> None:
    if path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    ):
        raise RuntimeError(f"refusing reparse point: {path}")


def _assert_within(path: Path, root: Path) -> None:
    target = Path(path).resolve()
    base = Path(root).resolve()
    if target != base and base not in target.parents:
        raise RuntimeError(f"path outside allowed root: {path}")


def current_sid() -> str:
    output = subprocess.run(
        ["whoami.exe", "/user"], capture_output=True, check=False
    ).stdout.decode("utf-8", "replace")
    for token in output.replace(",", " ").split():
        if token.startswith("S-1-"):
            return token
    raise RuntimeError("SID not found")


def group_names() -> list[str]:
    # SID values are independent of OS language and console code page.
    value = _ps("ConvertTo-Json -Compress -InputObject @([System.Security.Principal.WindowsIdentity]::GetCurrent().Groups | ForEach-Object { $_.Value })")
    return json.loads(value)


def sddl(path: Path) -> str:
    from app.isolation.win32 import get_sddl
    return get_sddl(path)


def deny(path: Path, sid: str, rights: str, run_root: Path) -> str:
    _assert_within(path, run_root)
    path = Path(path).resolve()
    from app.isolation.win32 import _acl_rule
    return _acl_rule(path, sid, run_root, allow=False, rights=rights).sddl


def restore(path: Path, value: str, run_root: Path, *, is_directory: bool | None = None) -> None:
    _assert_within(path, run_root)
    path = Path(path).resolve()
    from app.isolation.win32 import restore_sddl
    restore_sddl(path, value, is_directory=is_directory)


def read_ok(path: Path) -> dict:
    try:
        data = path.read_bytes()
        return {"ok": True, "size": len(data), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "size": None, "error": type(exc).__name__}


def read_denied(path: Path) -> dict:
    result = read_ok(path)
    return {"ok": not result["ok"], "read": result["ok"], "error": result["error"]}


def write_denied(path: Path) -> dict:
    target = path / "probe_write.tmp" if path.is_dir() else path
    created = target != path
    try:
        target.write_text("x", encoding="utf-8")
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        return {"ok": False, "write": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "write": False, "error": type(exc).__name__}


def loopback_blocked() -> dict:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = server.accept()
            connection.close()
        except OSError:
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            blocked = False
            error = None
    except Exception as exc:  # noqa: BLE001
        blocked = True
        error = type(exc).__name__
    finally:
        server.close()
    return {"blocked": blocked, "target": f"127.0.0.1:{port}", "error": error}


def external_blocked() -> dict:
    try:
        with socket.create_connection(("203.0.113.1", 443), timeout=2):
            return {"blocked": False, "target": "203.0.113.1:443", "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"blocked": True, "target": "203.0.113.1:443", "error": type(exc).__name__}


def job_check(win32, base: Path) -> dict:
    script = base / "job_child.py"
    pid_file = base / "job_pids.txt"
    script.write_text(
        "import os,sys,time,subprocess\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']).pid\n"
        "open(sys.argv[1],'w').write(str(os.getpid())+','+str(child))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    restricting_sid = win32.generate_restricting_sid()
    acl_changes = []
    process = None
    try:
        # The child writes job_pids.txt into base; the parent account SID
        # covers the normal check, the random SID covers the restricted check.
        acl_changes.append(
            win32.allow_sid(base, win32.current_user_sid(), base, root_allowed=True)
        )
        acl_changes.append(
            win32.allow_sid(base, restricting_sid, base, root_allowed=True)
        )
        # The script is created before the directory ACE; its default file
        # DACL may not inherit the restricting SID. Grant it explicitly,
        # otherwise the restricted child cannot read job_child.py.
        acl_changes.append(
            win32.allow_sid(script, win32.current_user_sid(), base, root_allowed=True)
        )
        acl_changes.append(
            win32.allow_sid(script, "S-1-3-4", base, root_allowed=True)
        )
        acl_changes.append(
            win32.allow_sid(script, restricting_sid, base, root_allowed=True)
        )
        process = win32.spawn_restricted(
            [sys.executable, "-I", str(script), str(pid_file)],
            cwd=base,
            env=win32.build_environment(),
            restricting_sid=restricting_sid,
            stdout_path=base / "job_out.txt",
            stderr_path=base / "job_err.txt",
        )
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.1)
        if not pid_file.exists():
            stderr = ""
            err_path = base / "job_err.txt"
            if err_path.exists():
                stderr = err_path.read_text(encoding="utf-8", errors="replace")[:500]
            return {"ok": False, "error": "no_pids", "stderr": stderr}
        worker_pid, child_pid = (int(x) for x in pid_file.read_text().split(","))
        in_job = win32.is_process_in_job(child_pid, process.job.handle)
        alive_before = win32.is_process_alive(worker_pid) and win32.is_process_alive(child_pid)
        process.job.terminate()
        time.sleep(1.0)
        alive_after = win32.is_process_alive(worker_pid) or win32.is_process_alive(child_pid)
        return {
            "ok": alive_before and in_job and not alive_after,
            "child_in_job": in_job,
            "alive_before": alive_before,
            "alive_after": alive_after,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    finally:
        if process is not None:
            process.close()
        try:
            win32.restore_acl(acl_changes)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"job ACL restore failed: {type(exc).__name__}") from exc


def _has_reparse(root: Path) -> bool:
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name
            if path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            ):
                return True
    return False


def write_evidence(evidence: dict, out_path: Path | None) -> None:
    """Emit lossless ASCII JSON, also valid UTF-8, even on a GBK stdout."""
    payload = json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2)
    if out_path is None:
        print(payload)
    else:
        out_path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", default="-", help="'-' for stdout (parent-captured)")
    parser.add_argument("--nonce", default="")
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        raise SystemExit("--project-root must be an existing directory")
    base = Path(args.base).resolve()
    allowed_roots = [
        (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ADLL-Account-SelfCheck").resolve(),
        (Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public")) / "ADLL-Account-SelfCheck").resolve(),
    ]
    if not any(base == root or root in base.parents for root in allowed_roots):
        raise SystemExit("--base must be under ProgramData/LOCALAPPDATA ADLL-Account-SelfCheck")
    _assert_not_reparse(base)
    base.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=base)).resolve()
    _assert_not_reparse(run)

    out_path: Path | None = None
    if args.out != "-":
        out_path = Path(args.out).resolve()
        if base == out_path or base in out_path.parents:
            raise SystemExit("--out must not be inside the account-writable base")

    sid = current_sid()
    evidence: dict = {
        "nonce": args.nonce,
        "sid": sid,
        "group_sids": group_names(),
        "base": str(run),
        "checks": {},
        "cleanup_errors": [],
        "network_is_informational": True,
        "self_check": {"status": "not_run", "ok": None},
        "generate": {"status": "not_run", "ok": None},
        "job": {"status": "not_run", "ok": None},
    }
    acl_restore: list[tuple[Path, str, bool]] = []
    adapter = None
    try:
        originals = run / "originals"
        (originals / "repo").mkdir(parents=True)
        (originals / "user").mkdir(parents=True)
        (originals / "repo" / "a.txt").write_text("REPO-SECRET", encoding="utf-8")
        (originals / "db.sqlite").write_text("DB-SECRET", encoding="utf-8")
        (originals / "user" / "notes.txt").write_text("USER-SECRET", encoding="utf-8")
        subset = run / "subset"
        subset.mkdir()
        (subset / "allowed.txt").write_text("ALLOWED", encoding="utf-8")

        # 1) 账户主体：对单独 protected 集合 Deny 自身 SID 后实测。
        protected = run / "account-protected"
        (protected / "repo").mkdir(parents=True)
        (protected / "user").mkdir(parents=True)
        (protected / "repo" / "a.txt").write_text("REPO-SECRET", encoding="utf-8")
        (protected / "db.sqlite").write_text("DB-SECRET", encoding="utf-8")
        (protected / "user" / "notes.txt").write_text("USER-SECRET", encoding="utf-8")
        for target, rights in (
            (protected / "repo", ACCOUNT_DENY_READ),
            (protected / "user", ACCOUNT_DENY_READ),
            (protected / "db.sqlite", ACCOUNT_DENY_READ_WRITE),
        ):
            is_directory = target.is_dir()
            acl_restore.append((target, deny(target, sid, rights, run), is_directory))
        evidence["account_deny_rights"] = {
            "repo": ACCOUNT_DENY_READ,
            "user": ACCOUNT_DENY_READ,
            "db": ACCOUNT_DENY_READ_WRITE,
            "read_control_retained": True,
        }
        evidence["checks"]["account_read_allowed"] = read_ok(subset / "allowed.txt")
        evidence["checks"]["account_repo_denied"] = read_denied(protected / "repo" / "a.txt")
        evidence["checks"]["account_db_denied"] = read_denied(protected / "db.sqlite")
        evidence["checks"]["account_user_denied"] = read_denied(protected / "user" / "notes.txt")
        evidence["checks"]["account_db_write_denied"] = write_denied(protected / "db.sqlite")

        # 2) 项目/真实目录访问（只读；用于判定生产 S10/S14）。
        project_file = project_root / "backend" / "pyproject.toml"
        evidence["checks"]["project_read"] = read_ok(project_file)
        evidence["checks"]["project_path"] = str(project_file)

        # 3) self_check（受限子进程 + 随机 restricting SID + DACL）。
        from app.agents.base import GenerationRequest
        from app.agents.worker import WorkerAgentAdapter

        adapter = WorkerAgentAdapter(
            endpoint="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
            model="qwen3.7-flash-2026-07-15",
            sandbox_root=run / "worker",
            acl_root=run,
            deny_read=(
                str(originals / "repo"),
                str(originals / "db.sqlite"),
                str(originals / "user"),
            ),
            deny_write=(str(originals / "db.sqlite"),),
            synthetic=True,
        )
        evidence["self_check"] = {"status": "running", "ok": None}
        report = adapter.self_check()
        evidence["self_check"] = {
            "status": "passed" if report.ok else "failed",
            "ok": report.ok,
            "details": report.details,
        }
        if not report.ok:
            from app.agents.dashscope import AdapterDisabled
            evidence["generate"]["reason"] = "self_check_failed"
            evidence["job"]["reason"] = "self_check_failed"
            raise AdapterDisabled("isolation_unverified")
        evidence["generate"] = {"status": "running", "ok": None}
        generated = adapter.generate(
            GenerationRequest(
                subset_path=None,
                requirement_text="ACCOUNT-SELFCHECK",
                feedback_texts=[],
                send_manifest={"source": []},
                payload={"model": "m", "max_tokens": 256, "messages": []},
            )
        )
        evidence["generate"] = {
            "status": "passed" if generated.text.startswith("SYNTHETIC_WORKER_PLAN") else "failed",
            "ok": generated.text.startswith("SYNTHETIC_WORKER_PLAN"),
            "usage_basis": generated.usage_basis,
            "cost_basis": generated.cost.get("basis"),
        }

        # 4) 网络：仅信息性记录；不得作为 OS 出站 allowlist PASS 证据。
        evidence["network"] = {
            "loopback": loopback_blocked(),
            "external_testnet": external_blocked(),
        }

        # 5) Job Object。
        from app.isolation import win32

        evidence["job"] = {"status": "running", "ok": None}
        evidence["job"] = job_check(win32, run)
        evidence["job"]["status"] = "passed" if evidence["job"].get("ok") else "failed"

        checks = [
            evidence["checks"]["account_read_allowed"]["ok"],
            evidence["checks"]["account_repo_denied"]["ok"],
            evidence["checks"]["account_db_denied"]["ok"],
            evidence["checks"]["account_user_denied"]["ok"],
            evidence["checks"]["account_db_write_denied"]["ok"],
            evidence["self_check"]["ok"],
            evidence["generate"]["ok"],
            evidence["job"]["ok"],
        ]
        evidence["ok"] = bool(checks) and all(checks)
        evidence["production_note"] = (
            "project_read.ok=True 表示实验账户仍可读项目目录 → 生产 S10/S14 不通过"
        )
    except Exception as exc:  # noqa: BLE001
        evidence["ok"] = False
        from app.isolation.win32 import error_details
        evidence["error"] = type(exc).__name__
        evidence["error_details"] = error_details(exc)
        if adapter is not None and getattr(adapter, "last_result", None):
            diagnostics = adapter.last_result.get("diagnostics")
            if diagnostics:
                evidence["generate"].setdefault("diagnostics", diagnostics)
        for name in ("self_check", "generate", "job"):
            if evidence[name].get("status") == "running":
                evidence[name].update(status="failed", ok=False)
            elif evidence[name].get("status") == "not_run":
                evidence[name].setdefault("reason", "earlier_stage_failed")
    finally:
        for path, value, is_directory in reversed(acl_restore):
            try:
                restore(path, value, run, is_directory=is_directory)
            except Exception as exc:  # noqa: BLE001
                from app.isolation.win32 import error_details
                evidence["cleanup_errors"].append(
                    {"stage": "acl_restore", "path": str(path), **error_details(exc)}
                )
        try:
            if _has_reparse(run):
                raise RuntimeError("reparse_point_in_run")
            shutil.rmtree(run)
        except Exception as exc:  # noqa: BLE001
            evidence["cleanup_errors"].append(f"rmtree:{type(exc).__name__}")
        if evidence["cleanup_errors"]:
            evidence["ok"] = False
        write_evidence(evidence, out_path)
    return 0 if evidence.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
