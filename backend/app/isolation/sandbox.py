"""受限 worker sandbox：物化子集、DACL Deny、权限探针与 Job Object 生命周期。

父进程（后端）负责：
1. 在配置的 `sandbox_root` 下创建临时 sandbox（只放本次授权子集与 job JSON）；
2. 对原仓库/审批 DB/用户目录/凭据等客体添加 `Deny <restricting SID>`；
3. 以受限令牌启动探针，只有真实探针证据全部通过才允许启动 worker；
4. 以受限令牌 + Job Object 启动 worker；超时/关闭终止整个进程树。

worker 自身不持有数据库/审批服务引用，也不接收原仓库路径。
"""
from __future__ import annotations

import hashlib
import json
import sys
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .win32 import (
    AclChange,
    AclOperationError,
    allow_sid,
    current_user_sid,
    deny_sid,
    error_details,
    generate_restricting_sid,
    get_sddl,
    restore_acl,
    spawn_restricted,
)

def default_python() -> str:
    """Interpreter for the restricted child: prefer the base install.

    A venv redirector needs a readable `pyvenv.cfg` next to itself; after the
    project ACL hardening the checkout is intentionally unreadable to the
    restricted token. The base interpreter only needs the stdlib, which is
    world-readable and is what production staging pins as well.
    """
    base = getattr(sys, "_base_executable", None)
    if base and Path(base).is_file():
        return str(base)
    return sys.executable


PROBE_SCRIPT = Path(__file__).with_name("probe_main.py")
WORKER_SCRIPT = Path(__file__).with_name("worker_main.py")
# 诊断只保留有界尾部，绝不复制文件内容/环境变量/请求体。
DIAGNOSTIC_TAIL_CHARS = 4096


def _read_tail(path: Path | None, limit: int = DIAGNOSTIC_TAIL_CHARS) -> str | None:
    """Read a bounded tail before the sandbox is deleted.

    probe_main/worker_main never log payloads, credentials or file contents;
    their stderr is therefore safe to retain. The cap and truncation marker
    keep a pathological traceback from bloating the evidence file.
    """
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit * 4:
                handle.seek(size - limit * 4)
            data = handle.read(limit * 4)
    except OSError as exc:
        return f"<unreadable:{type(exc).__name__}>"
    text = data.decode("utf-8", "replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > limit:
        text = "...[truncated]...\n" + text[-limit:]
    return text


def _process_diagnostics(
    *,
    exit_code: int | None,
    timed_out: bool,
    evidence_path: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> dict:
    evidence_exists = evidence_path.is_file()
    try:
        evidence_size = evidence_path.stat().st_size if evidence_exists else None
    except OSError:
        evidence_size = None
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "evidence_file": {"exists": evidence_exists, "size": evidence_size},
        "stdout_tail": _read_tail(stdout_path),
        "stderr_tail": _read_tail(stderr_path),
    }


class IsolationError(RuntimeError):
    pass


@dataclass
class IsolationSpec:
    sandbox_root: Path
    acl_root: Path | None = None
    deny_read: tuple[Path, ...] = ()
    deny_write: tuple[Path, ...] = ()
    restricting_sid: str | None = None
    python_executable: str | None = None
    process_timeout_seconds: int = 30

    def resolved_python(self) -> str:
        return self.python_executable or default_python()

    def resolved_acl_root(self) -> Path:
        return Path(self.acl_root or self.sandbox_root)


@dataclass
class ProbeResult:
    ok: bool
    evidence: dict
    error: str | None = None


@dataclass
class Sandbox:
    spec: IsolationSpec
    root: Path = field(init=False)
    subset_dir: Path = field(init=False)
    work_dir: Path = field(init=False)
    restricting_sid: str = field(init=False)
    parent_sid: str = field(init=False)
    _acl_changes: list[AclChange] = field(default_factory=list)
    _closed: bool = False
    _process: object | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        try:
            self._initialize()
        except Exception as primary:
            try:
                if hasattr(self, "root"):
                    self.close()
            except Exception as cleanup:
                raise AclOperationError("sandbox_initialize", {
                    "primary": error_details(primary), "cleanup": error_details(cleanup)
                }) from primary
            raise

    def _allow_restricted_read(
        self, path: Path, *, rights: str = "ReadAndExecute, Synchronize"
    ) -> None:
        """Give both halves of the restricted access check a direct ACE.

        A restricted token must pass the normal check and the restricting-SID
        check. Windows/CRT-created files can carry a protected default DACL
        that neither inherits the parent's restricting-SID ACE nor grants the
        owner (OWNER RIGHTS). Write both an OWNER RIGHTS Allow and a
        restricting-SID Allow on every parent-created object the child reads.

        Default is read+execute only: the worker must never be able to modify
        the scripts or the authorized subset it executes/reads. `work_dir` is
        the single exception and gets Modify explicitly.
        """
        acl_root = self.spec.resolved_acl_root()
        # Parent account SID covers the normal check even if the file owner
        # placeholder is not effective; OWNER RIGHTS is kept as a second
        # safety net, and the random SID covers the restricting check.
        for sid in (self.parent_sid, "S-1-3-4", self.restricting_sid):
            self._acl_changes.append(
                allow_sid(path, sid, acl_root, rights=rights, root_allowed=True)
            )

    def _stage_script(self, source: Path, name: str) -> tuple[Path, str]:
        """Copy the stdlib-only script into the sandbox (read-only for worker).

        The project checkout may be unreadable to the restricted token (and a
        worker-writable path must never supply executable code). The sandbox
        copy is byte-identical, hash-recorded, and granted read+execute only.
        """
        data = source.read_bytes()
        target = self.script_dir / name
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self._allow_restricted_read(target)
        return target, digest

    @staticmethod
    def _script_tampered(path: Path, expected_sha256: str) -> bool:
        """Re-hash the staged script immediately before every launch."""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256
        except OSError:
            return True

    def _allow_traverse(self, path: Path) -> None:
        """Grant the restricted token traverse-only access to an ancestor.

        `tempfile.mkdtemp` creates `run/worker` with a protected default DACL
        (OWNER RIGHTS/SYSTEM/Administrators); it does not inherit the test
        base's Users Traverse ACE. The restricted check then fails before the
        child can reach the sandbox root. Traverse-only keeps these ancestors
        unlistable and unreadable.
        """
        self._acl_changes.append(
            allow_sid(
                path,
                "S-1-5-32-545",  # BUILTIN\\Users
                self.spec.resolved_acl_root(),
                rights="Traverse, ReadAttributes, Synchronize",
                root_allowed=True,
            )
        )

    def _bounded_sddl(self, path: Path, limit: int = 2048) -> str | None:
        try:
            return get_sddl(path)[:limit]
        except Exception:  # noqa: BLE001
            return None

    def _file_has_restricting_sid(self, path: Path) -> bool | None:
        try:
            return self.restricting_sid in get_sddl(path)
        except Exception:  # noqa: BLE001
            return None

    def _initialize(self) -> None:
        root_base = Path(self.spec.sandbox_root)
        root_base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=root_base, prefix="adll-worker-"))
        self.subset_dir = self.root / "subset"
        self.work_dir = self.root / "work"
        self.script_dir = self.root / "scripts"
        self.subset_dir.mkdir()
        self.work_dir.mkdir()
        self.script_dir.mkdir()
        self.restricting_sid = self.spec.restricting_sid or generate_restricting_sid()
        self.parent_sid = current_user_sid()
        acl_root = self.spec.resolved_acl_root()
        # run/worker 由 mkdtemp/CRT 创建，默认 DACL 是受保护的
        # OWNER RIGHTS/SYSTEM/Administrators，不继承测试基目录的 Users
        # Traverse；必须先给这两个祖先目录补 traverse，受限子进程才能到达
        # sandbox 根。它们仍不可列目录/读文件。
        for ancestor in dict.fromkeys((acl_root, root_base)):
            self._allow_traverse(ancestor)
        # 显式授予受限 SID 对 sandbox 的读写。子目录在授予前已创建，且父级
        # DACL 可能是受保护/仅 OWNER RIGHTS 的受保护描述符；不依赖继承传播，
        # 对 root/subset/work 分别写 ACE，避免受限子进程在启动阶段被拒绝。
        # 可执行代码与授权子集只读；只有 work_dir 允许 worker 写结果。
        for read_only_path in (self.root, self.subset_dir, self.script_dir):
            self._allow_restricted_read(read_only_path)
        self._allow_restricted_read(self.work_dir, rights="Modify, Synchronize")
        self.probe_script, self.probe_script_sha256 = self._stage_script(
            PROBE_SCRIPT, "probe_main.py"
        )
        self.worker_script, self.worker_script_sha256 = self._stage_script(
            WORKER_SCRIPT, "worker_main.py"
        )
        for path in self.spec.deny_read:
            self._acl_changes.append(
                deny_sid(Path(path), self.restricting_sid, acl_root)
            )
        for path in self.spec.deny_write:
            self._acl_changes.append(
                deny_sid(Path(path), self.restricting_sid, acl_root)
            )

    def write_subset(self, files: dict[str, bytes]) -> list[dict]:
        entries = []
        for name, content in sorted(files.items()):
            target = self.subset_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            self._allow_restricted_read(target)
            entries.append(
                {
                    "name": name,
                    "path": str(target),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        return entries

    def _preflight(self, spec_path: Path, out_path: Path, allowed: list[dict]) -> dict:
        """Record the conditions that decide whether the restricted probe can start.

        Only names/booleans/sizes are recorded. `get_sddl` is read-only and is
        attempted after a failure, before the sandbox is deleted. A readable
        directory is not sufficient: each parent-created file must carry the
        restricting-SID ACE itself.
        """
        python = self.spec.resolved_python()
        acl_root = self.spec.resolved_acl_root()
        root_base = Path(self.spec.sandbox_root)
        sample = allowed[0]["path"] if allowed else None
        info = {
            "python_executable": python,
            "python_executable_exists": Path(python).is_file(),
            "probe_script": str(self.probe_script),
            "probe_script_exists": self.probe_script.is_file(),
            "probe_script_sha256": self.probe_script_sha256,
            "worker_script_sha256": self.worker_script_sha256,
            "python_is_base_install": Path(python).resolve()
            == Path(default_python()).resolve(),
            "work_dir": str(self.work_dir),
            "parent_sid": self.parent_sid,
            "spec_exists": spec_path.is_file(),
            "spec_has_restricting_sid": self._file_has_restricting_sid(spec_path),
            "spec_sddl": self._bounded_sddl(spec_path),
            "work_dir_sddl": self._bounded_sddl(self.work_dir),
            "acl_root": str(acl_root),
            "acl_root_sddl": self._bounded_sddl(acl_root),
            "root_base": str(root_base),
            "root_base_sddl": self._bounded_sddl(root_base),
            "sandbox_root": str(self.root),
            "sandbox_root_sddl": self._bounded_sddl(self.root),
            "work_parent_sddl": self._bounded_sddl(acl_root.parent),
            "base_sddl": self._bounded_sddl(acl_root.parent.parent),
            "out_exists": out_path.is_file(),
            "allowed_sample": sample,
            "allowed_sample_has_restricting_sid": (
                self._file_has_restricting_sid(Path(sample)) if sample else None
            ),
            "work_dir_has_restricting_sid": self._file_has_restricting_sid(
                self.work_dir
            ),
        }
        return info

    def probe(
        self,
        allowed: list[dict],
        *,
        extra_deny_read: tuple[Path, ...] = (),
        extra_deny_write: tuple[Path, ...] = (),
    ) -> ProbeResult:
        deny_read = (*self.spec.deny_read, *extra_deny_read)
        deny_write = (*self.spec.deny_write, *extra_deny_write)
        spec = {
            "allowed_read": allowed,
            "deny_read": [
                {"name": f"deny_read_{index}", "path": str(path)}
                for index, path in enumerate(deny_read)
            ],
            "deny_write": [
                {
                    "name": f"deny_write_{index}",
                    "path": str(Path(path) / f"adll_probe_write_{index}.tmp")
                    if Path(path).is_dir()
                    else str(path),
                }
                for index, path in enumerate(deny_write)
            ],
        }
        if self._script_tampered(self.probe_script, self.probe_script_sha256):
            return ProbeResult(False, {"error": "script_tampered"}, "script_tampered")
        spec_path = self.work_dir / "probe_spec.json"
        out_path = self.work_dir / "probe_evidence.json"
        stdout_path = self.work_dir / "probe_stdout.txt"
        stderr_path = self.work_dir / "probe_stderr.txt"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        self._allow_restricted_read(spec_path)
        token_restricted = False
        token_sids: list[str] = []
        token_attrs: dict[str, int] = {}

        def failure(error: str, *, exit_code: int | None = None, timed_out: bool = False) -> ProbeResult:
            # Capture before Sandbox.close() deletes work_dir; the returned
            # evidence outlives the sandbox and reaches account_selfcheck.
            diagnostics = _process_diagnostics(
                exit_code=exit_code,
                timed_out=timed_out,
                evidence_path=out_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            diagnostics["preflight"] = self._preflight(spec_path, out_path, allowed)
            diagnostics["token"] = {
                "restricted": token_restricted,
                "restricting_sids": token_sids,
                "restricting_sid_attributes": token_attrs,
                "has_restricting_sid": self.restricting_sid in token_sids,
                "restricting_sid_attributes_value": token_attrs.get(
                    self.restricting_sid
                ),
            }
            return ProbeResult(False, {"diagnostics": diagnostics}, error=error)

        try:
            process = spawn_restricted(
                [self.spec.resolved_python(), "-I", str(self.probe_script), str(spec_path), str(out_path)],
                cwd=self.work_dir,
                env=_probe_environment(),
                restricting_sid=self.restricting_sid,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except OSError as exc:
            return failure(f"probe_spawn:{type(exc).__name__}")
        exit_code: int | None = None
        try:
            exit_code = process.wait(self.spec.process_timeout_seconds * 1000)
            token_restricted = process.token_restricted
            token_sids = list(process.restricting_sids)
            token_attrs = dict(process.restricting_sid_attributes)
        except TimeoutError:
            return failure("probe_timeout", timed_out=True)
        except Exception as exc:  # noqa: BLE001
            return failure(f"probe_wait:{type(exc).__name__}")
        finally:
            process.close()
        if not out_path.exists():
            return failure(f"probe_no_evidence:exit_{exit_code}", exit_code=exit_code)
        try:
            evidence = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result = failure(
                f"probe_evidence_invalid:{type(exc).__name__}", exit_code=exit_code
            )
            result.evidence["diagnostics"]["evidence_error"] = type(exc).__name__
            return result
        if not isinstance(evidence, dict):
            result = failure("probe_evidence_not_object", exit_code=exit_code)
            result.evidence["diagnostics"]["evidence_error"] = "not_object"
            return result
        evidence["token_restricted"] = token_restricted
        # 父进程独立复核 allowed 文件哈希（worker 只报告可读与长度）。
        allowed_ok = True
        for entry in allowed:
            target = Path(entry["path"])
            try:
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError:
                allowed_ok = False
                continue
            allowed_ok = allowed_ok and digest == entry["sha256"]
        evidence["allowed_digest_match"] = allowed_ok
        ok = bool(evidence.get("probe_checks_ok")) and token_restricted and allowed_ok
        evidence["ok"] = ok
        return ProbeResult(
            ok, evidence, error=None if ok else f"probe_failed:exit_{exit_code}"
        )

    def run(
        self,
        job: dict,
        *,
        env_extra: dict[str, str] | None = None,
        body_bytes: bytes | None = None,
    ) -> dict:
        if self._script_tampered(self.worker_script, self.worker_script_sha256):
            return {"ok": False, "error": "script_tampered", "sent": False}
        job_path = self.work_dir / "job.json"
        result_path = self.work_dir / "result.json"
        sent_marker = self.work_dir / "sent.marker"
        job = {**job, "work_dir": str(self.work_dir)}
        body_path: Path | None = None
        if body_bytes is not None:
            body_path = self.work_dir / "request_body.bin"
            body_path.write_bytes(body_bytes)
            self._allow_restricted_read(body_path)
            job = {**job, "body_file": str(body_path)}
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        self._allow_restricted_read(job_path)
        env = _probe_environment()
        if env_extra:
            env.update(env_extra)
        stdout_path = self.work_dir / "worker_stdout.txt"
        stderr_path = self.work_dir / "worker_stderr.txt"

        def failure(error: str, *, exit_code: int | None = None, timed_out: bool = False) -> dict:
            diagnostics = _process_diagnostics(
                exit_code=exit_code,
                timed_out=timed_out,
                evidence_path=result_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            diagnostics["preflight"] = {
                "job_exists": job_path.is_file(),
                "job_has_restricting_sid": self._file_has_restricting_sid(job_path),
                "body_path": str(body_path) if body_path is not None else None,
                "body_has_restricting_sid": (
                    self._file_has_restricting_sid(body_path)
                    if body_path is not None
                    else None
                ),
            }
            diagnostics["token"] = {
                "restricted": bool(process.token_restricted) if process else False,
                "restricting_sids": list(process.restricting_sids) if process else [],
                "restricting_sid_attributes": (
                    dict(process.restricting_sid_attributes) if process else {}
                ),
                "has_restricting_sid": (
                    self.restricting_sid in process.restricting_sids
                    if process
                    else False
                ),
                "restricting_sid_attributes_value": (
                    process.restricting_sid_attributes.get(self.restricting_sid)
                    if process
                    else None
                ),
            }
            return {
                "ok": False,
                "error": error,
                "sent": sent_marker.exists(),
                "diagnostics": diagnostics,
            }

        process = None
        try:
            process = spawn_restricted(
                [self.spec.resolved_python(), "-I", str(self.worker_script), str(job_path), str(result_path)],
                cwd=self.work_dir,
                env=env,
                restricting_sid=self.restricting_sid,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except OSError as exc:
            return failure(f"spawn:{type(exc).__name__}")
        self._process = process
        exit_code: int | None = None
        try:
            exit_code = process.wait(self.spec.process_timeout_seconds * 1000)
        except TimeoutError:
            return failure("worker_timeout", timed_out=True)
        except Exception as exc:  # noqa: BLE001
            return failure(f"worker_wait:{type(exc).__name__}")
        finally:
            self._process = None
            if process is not None:
                process.close()
        if not result_path.exists():
            return failure(f"worker_no_result:exit_{exit_code}", exit_code=exit_code)
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result = failure(
                f"worker_result_invalid:{type(exc).__name__}", exit_code=exit_code
            )
            result["diagnostics"]["result_error"] = type(exc).__name__
            return result
        if not isinstance(result, dict):
            result = failure("worker_result_not_object", exit_code=exit_code)
            result["diagnostics"]["result_error"] = "not_object"
            return result
        return result

    def cancel(self) -> bool:
        """终止当前 worker 进程树；返回是否确有运行中的 worker。"""
        process = self._process
        if process is None:
            return False
        try:
            process.job.terminate()
        except Exception:  # noqa: BLE001
            return False
        return True

    def close(self) -> None:
        if self._closed:
            return
        restore_acl(self._acl_changes)
        self._acl_changes.clear()
        shutil.rmtree(self.root)
        self._closed = True

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.close()
        except Exception as cleanup:
            if exc[1] is not None:
                raise AclOperationError("sandbox_exit", {
                    "primary": error_details(exc[1]), "cleanup": error_details(cleanup)
                }) from exc[1]
            raise


def _probe_environment() -> dict[str, str]:
    # 最小环境：不传递 DASHSCOPE_API_KEY / 代理 / 用户 PYTHONPATH。
    from .win32 import build_environment

    return build_environment()
