"""Git CLI 子进程适配器（ADR-C3）。

安全约束（FV-0 边界）：
- 参数数组 + shell=False + 超时 + 显式净化环境；
- 仅只读命令（rev-parse/status/ls-tree/cat-file/show），不执行 checkout/reset/clean/stash/fetch；
- 路径必须经白名单根校验（realpath 包含关系），并为仓库根；
- 不执行仓库脚本/Hook（只读命令不触发 Hook；环境隔离 gitconfig）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field


class GitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class SnapshotReport:
    available: bool
    commit_sha: str
    object_format: str
    entry_count: int = 0
    symlink_count: int = 0
    gitlink_count: int = 0
    digest: str | None = None
    reason: str | None = None
    summary: dict = field(default_factory=dict)


class GitAdapter:
    def __init__(self, allowed_roots: list[str], timeout: int = 30) -> None:
        self.allowed_roots = [os.path.normcase(os.path.realpath(r)) for r in allowed_roots]
        self.timeout = timeout

    # ---- environment / execution ----
    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        env.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "LC_ALL": "C",
            }
        )
        return env

    def _run(self, path: str, args: list[str]) -> tuple[int, str, str]:
        cmd = ["git", "-C", path, *args]
        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError("git_timeout", f"command timed out: {args}") from exc
        except OSError as exc:
            raise GitError("git_unavailable", str(exc)) from exc
        return proc.returncode, proc.stdout, proc.stderr

    def _git(self, path: str, args: list[str]) -> str:
        code, out, err = self._run(path, args)
        if code != 0:
            raise GitError("git_failed", err.strip() or f"exit {code}")
        return out.strip()

    def _run_bytes(self, path: str, args: list[str]) -> tuple[int, bytes, bytes]:
        cmd = ["git", "-C", path, *args]
        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError("git_timeout", f"command timed out: {args}") from exc
        except OSError as exc:
            raise GitError("git_unavailable", str(exc)) from exc
        return proc.returncode, proc.stdout, proc.stderr

    def archive_entries(self, path: str, sha: str, max_bytes: int = 50_000_000) -> list[dict]:
        """`git archive --format=tar` 的条目清单（只读；用于 tree/归档一致性核验）。"""
        import io
        import tarfile

        code, out, err = self._run_bytes(path, ["archive", "--format=tar", sha])
        if code != 0:
            raise GitError(
                "git_failed", err.decode("utf-8", "replace").strip() or f"exit {code}"
            )
        if len(out) > max_bytes:
            raise GitError("archive_too_large", str(len(out)))
        entries: list[dict] = []
        with tarfile.open(fileobj=io.BytesIO(out), mode="r:") as tar:
            for member in tar.getmembers():
                self._check_paths_safe([member.name])
                if member.isfile():
                    handle = tar.extractfile(member)
                    content = handle.read() if handle else b""
                    entries.append(
                        {
                            "name": member.name,
                            "type": "file",
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    )
                elif member.issym():
                    entries.append(
                        {"name": member.name, "type": "symlink", "linkname": member.linkname}
                    )
                elif member.isdir():
                    entries.append({"name": member.name, "type": "dir"})
                else:
                    entries.append({"name": member.name, "type": "other"})
        return entries

    def blob_bytes(self, path: str, sha: str, max_bytes: int = 50_000_000) -> bytes:
        code, out, err = self._run_bytes(path, ["cat-file", "blob", sha])
        if code != 0:
            raise GitError(
                "git_failed", err.decode("utf-8", "replace").strip() or f"exit {code}"
            )
        if len(out) > max_bytes:
            raise GitError("blob_too_large", str(len(out)))
        return out

    def show_file(self, path: str, sha: str, filename: str) -> str | None:
        code, out, _err = self._run(path, ["show", f"{sha}:{filename}"])
        return out if code == 0 else None

    def supports_check_attr_source(self, path: str, sha: str) -> bool:
        """核查 `git check-attr --source=<commit>` 在本机是否支持。"""
        code, _out, _err = self._run(
            path, ["check-attr", f"--source={sha}", "export-ignore", "--", "."]
        )
        return code == 0

    def attr_map(self, path: str, sha: str, names: list[str], paths: list[str]):
        """按 Commit 精确查询属性。返回 {path: {attr: value}}；不支持时返回 None。"""
        if not paths:
            return {}
        result: dict[str, dict] = {}
        chunk_size = 100
        for start in range(0, len(paths), chunk_size):
            chunk = paths[start : start + chunk_size]
            code, out, err = self._run(
                path, ["check-attr", f"--source={sha}", *names, "--", *chunk]
            )
            if code != 0:
                return None
            for line in out.splitlines():
                parts = line.split(": ", 2)
                if len(parts) != 3:
                    continue
                name, attr, value = parts
                result.setdefault(name, {})[attr] = value
        return result

    # ---- path validation ----
    def validate_path(self, path: str) -> str:
        if not path or "\x00" in path:
            raise GitError("invalid_path", "empty or invalid path")
        real = os.path.normcase(os.path.realpath(path))
        if not os.path.isdir(real):
            raise GitError("invalid_path", "path is not a directory")
        for root in self.allowed_roots:
            try:
                if os.path.commonpath([real, root]) == root:
                    return real
            except ValueError:
                continue
        raise GitError("path_not_authorized", "path outside authorized roots")

    def repo_root(self, path: str) -> str:
        real = self.validate_path(path)
        code, out, err = self._run(real, ["rev-parse", "--show-toplevel"])
        out = out.strip()
        if code != 0 or not out:
            raise GitError("not_git_repository", err.strip() or "not a git repository")
        top = os.path.normcase(os.path.realpath(out))
        if top != real:
            raise GitError("not_repository_root", "path must be the repository root")
        return top

    # ---- read-only facts ----
    def repo_identity(self, path: str) -> str:
        return self.repo_root(path)

    def object_format(self, path: str) -> str:
        value = self._git(path, ["rev-parse", "--show-object-format"])
        if value not in {"sha1", "sha256"}:
            raise GitError("unsupported_object_format", value)
        return value

    def commit_sha(self, path: str) -> str:
        return self._git(path, ["rev-parse", "HEAD"])

    def branch(self, path: str) -> str | None:
        code, out, _ = self._run(path, ["symbolic-ref", "--short", "HEAD"])
        out = out.strip()
        return out if code == 0 and out else None

    def workspace_status(self, path: str) -> dict:
        code, out, err = self._run(
            path, ["status", "--porcelain=v1", "--untracked-files=all"]
        )
        if code != 0:
            raise GitError("git_failed", err.strip() or f"exit {code}")
        lines = [line for line in out.splitlines() if line.strip()]
        staged = modified = untracked = 0
        for line in lines:
            if line.startswith("??"):
                untracked += 1
            else:
                x, y = line[0], line[1]
                if x not in " ?":
                    staged += 1
                if y not in " ?":
                    modified += 1
        return {
            "clean": not lines,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "entries": lines,
        }

    def commit_exists(self, path: str, sha: str) -> bool:
        code, _, _ = self._run(path, ["cat-file", "-e", f"{sha}^{{commit}}"])
        return code == 0

    def tree_entries(self, path: str, sha: str) -> list[dict]:
        out = self._git(path, ["ls-tree", "-r", "-l", sha])
        entries = []
        for line in out.splitlines():
            if not line.strip():
                continue
            meta, _, name = line.partition("\t")
            parts = meta.split()
            if len(parts) < 4:
                raise GitError("snapshot_malformed", f"unexpected ls-tree line: {line}")
            mode, typ, obj, size = parts[0], parts[1], parts[2], parts[3]
            entries.append(
                {
                    "path": name,
                    "mode": mode,
                    "type": typ,
                    "object": obj,
                    "size": None if size == "-" else int(size),
                }
            )
        return entries

    @staticmethod
    def _check_paths_safe(names: list[str]) -> None:
        for name in names:
            if not name:
                raise GitError("path_traversal", "empty path")
            if os.path.isabs(name) or name.startswith(("/", "\\")):
                raise GitError("path_traversal", f"absolute path: {name}")
            parts = name.replace("\\", "/").split("/")
            if ".." in parts:
                raise GitError("path_traversal", f"parent traversal: {name}")

    def verify_snapshot(self, path: str, sha: str) -> SnapshotReport:
        objfmt = self.object_format(path)
        if not self.commit_exists(path, sha):
            return SnapshotReport(
                available=False,
                commit_sha=sha,
                object_format=objfmt,
                reason="commit_missing",
                summary={"reason": "commit_missing"},
            )
        try:
            entries = self.tree_entries(path, sha)
        except GitError as exc:
            return SnapshotReport(
                available=False,
                commit_sha=sha,
                object_format=objfmt,
                reason=exc.code,
                summary={"reason": exc.code, "message": exc.message},
            )
        names = [e["path"] for e in entries]
        try:
            self._check_paths_safe(names)
        except GitError as exc:
            return SnapshotReport(
                available=False,
                commit_sha=sha,
                object_format=objfmt,
                reason=exc.code,
                summary={"reason": exc.code, "message": exc.message},
            )

        symlinks = [e for e in entries if e["mode"] == "120000"]
        gitlinks = [e for e in entries if e["mode"] == "160000"]

        attr_code, attr_text, _ = self._run(path, ["show", f"{sha}:.gitattributes"])
        attrs = attr_text if attr_code == 0 else ""
        has_export_ignore = "export-ignore" in attrs
        has_export_subst = "export-subst" in attrs
        has_lfs = "filter=lfs" in attrs or "lfs" in attrs

        warnings: list[str] = []
        if symlinks:
            warnings.append(f"symlink entries: {len(symlinks)} (flagged, not silently treated as regular)")
        if gitlinks:
            warnings.append(f"gitlink/submodule entries: {len(gitlinks)} (content absent; flagged)")
        if has_export_ignore:
            warnings.append("export-ignore present (.gitattributes): archive excludes those paths (FV-0)")
        if has_export_subst:
            warnings.append("export-subst present: archive expands placeholders (FV-0)")
        if has_lfs:
            warnings.append("LFS filter present: archive keeps pointers, no smudge (FV-0)")

        canonical = json.dumps(
            sorted(
                [{"p": e["path"], "m": e["mode"], "o": e["object"], "s": e["size"]} for e in entries],
                key=lambda x: (x["p"], x["m"], x["o"]),
            ),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        summary = {
            "entry_count": len(entries),
            "symlink_count": len(symlinks),
            "gitlink_count": len(gitlinks),
            "export_ignore": has_export_ignore,
            "export_subst": has_export_subst,
            "lfs": has_lfs,
            "warnings": warnings,
        }
        return SnapshotReport(
            available=True,
            commit_sha=sha,
            object_format=objfmt,
            entry_count=len(entries),
            symlink_count=len(symlinks),
            gitlink_count=len(gitlinks),
            digest=digest,
            summary=summary,
        )