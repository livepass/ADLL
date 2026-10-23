"""可信 Commit 源码快照与物化授权子集（T028）。

- 仅从绑定的完整 Commit 读取（tree/blob/archive）。
- 核验 `git archive` 与 `git ls-tree` 内容一致性（export-subst 除外）。
- 明确处理 export-ignore / LFS / submodule / symlink / 路径逃逸；
  不跟随符号链接；默认排除敏感文件；无法验证 → fail-closed。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from dataclasses import dataclass, field

from ..adapters.git import GitAdapter, GitError

SENSITIVE_PATTERNS = (
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "*secret*",
    "*credential*",
    ".git/*",
)

SYMLINK_ESCAPE_WARNING = "symlink target escapes repository (not followed, excluded)"


@dataclass
class Materialization:
    available: bool
    reason: str | None = None
    files: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    digest: str | None = None
    lfs_pointers: list[str] = field(default_factory=list)


def _extract_patterns(attributes: str, token: str) -> list[str]:
    patterns = []
    for line in attributes.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and token in parts[1:]:
            patterns.append(parts[0].lstrip("/"))
    return patterns


def _matches(patterns: list[str], name: str) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if name == pattern or name.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def _is_sensitive(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(base, pattern)
        for pattern in SENSITIVE_PATTERNS
    )


def _symlink_escapes(linkname: str) -> bool:
    return os.path.isabs(linkname) or linkname.startswith("../") or "/../" in linkname


def verify_materialized(dest_dir: str, files: list[dict]) -> dict:
    """复核物化归档：缺失、内容哈希不符、清单外文件均视为篡改。"""
    base = os.path.realpath(dest_dir)
    expected = {entry["path"]: entry["sha256"] for entry in files}
    missing: list[str] = []
    mismatched: list[str] = []
    for name, digest in expected.items():
        target = os.path.realpath(os.path.join(base, name))
        if os.path.commonpath([base, target]) != base:
            mismatched.append(name)
            continue
        if not os.path.isfile(target):
            missing.append(name)
            continue
        with open(target, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        if actual != digest:
            mismatched.append(name)
    extra: list[str] = []
    for directory, _dirs, names in os.walk(base):
        for name in names:
            full = os.path.realpath(os.path.join(directory, name))
            relative = os.path.relpath(full, base).replace(os.sep, "/")
            if relative not in expected:
                extra.append(relative)
    return {
        "ok": not (missing or mismatched or extra),
        "missing": sorted(missing),
        "mismatched": sorted(mismatched),
        "extra": sorted(extra),
    }


def materialize(
    git: GitAdapter,
    repo_path: str,
    commit_sha: str,
    authorized_paths: list[str] | None = None,
    dest_dir: str | None = None,
) -> Materialization:
    try:
        tree = git.tree_entries(repo_path, commit_sha)
    except GitError as exc:
        return Materialization(False, exc.code)

    tree_map = {entry["path"]: entry for entry in tree}
    attributes = git.show_file(repo_path, commit_sha, ".gitattributes") or ""
    export_ignore = _extract_patterns(attributes, "export-ignore")
    export_subst = _extract_patterns(attributes, "export-subst")

    # 属性必须按绑定 Commit 精确核验；本机不支持 --source 时 fail-closed（不发送）。
    if not git.supports_check_attr_source(repo_path, commit_sha):
        return Materialization(False, "attribute_verification_unavailable")
    attr_map = git.attr_map(
        repo_path, commit_sha, ["export-ignore", "export-subst"], list(tree_map)
    )
    if attr_map is None:
        return Materialization(False, "attribute_verification_unavailable")
    attr_mode = "check-attr-source"

    def path_export_ignore(name: str) -> bool:
        if name in attr_map:
            return attr_map[name].get("export-ignore") == "set"
        return _matches(export_ignore, name)

    def path_export_subst(name: str) -> bool:
        if name in attr_map:
            return attr_map[name].get("export-subst") == "set"
        return _matches(export_subst, name)

    try:
        archive = git.archive_entries(repo_path, commit_sha)
    except GitError as exc:
        return Materialization(False, exc.code)

    warnings: list[str] = []
    for entry in archive:
        if entry["type"] == "symlink" and _symlink_escapes(entry.get("linkname", "")):
            warnings.append(SYMLINK_ESCAPE_WARNING)
    if export_ignore:
        warnings.append(f"export-ignore patterns: {export_ignore} (excluded from archive)")
    if export_subst:
        warnings.append(f"export-subst patterns: {export_subst} (archive expands placeholders)")
    warnings.append(f"attribute_mode={attr_mode}")

    archive_files = {e["name"]: e for e in archive if e["type"] == "file"}
    for name, arch in archive_files.items():
        if name not in tree_map:
            return Materialization(False, "archive_tree_mismatch")
        if path_export_subst(name):
            continue  # export-subst 会改变内容，跳过内容比对（已告警）
        try:
            blob = git.blob_bytes(repo_path, tree_map[name]["object"])
        except GitError as exc:
            return Materialization(False, exc.code)
        if hashlib.sha256(blob).hexdigest() != arch["sha256"]:
            return Materialization(False, "archive_content_mismatch")

    authorized = set(authorized_paths) if authorized_paths is not None else None
    files: list[dict] = []
    excluded: list[dict] = []
    lfs: list[str] = []
    for name, entry in sorted(tree_map.items()):
        if entry["mode"] == "160000":
            excluded.append({"path": name, "reason": "gitlink"})
            continue
        if entry["mode"] == "120000":
            excluded.append({"path": name, "reason": "symlink"})
            continue
        if path_export_ignore(name):
            excluded.append({"path": name, "reason": "export-ignore"})
            continue
        if _is_sensitive(name):
            excluded.append({"path": name, "reason": "sensitive"})
            continue
        if authorized is not None and name not in authorized:
            excluded.append({"path": name, "reason": "not_authorized"})
            continue
        try:
            blob = git.blob_bytes(repo_path, entry["object"])
        except GitError as exc:
            return Materialization(False, exc.code)
        digest = hashlib.sha256(blob).hexdigest()
        if blob.startswith(b"version https://git-lfs"):
            # LFS 指针不是真实内容；不静默发送（显式排除并记录）。
            lfs.append(name)
            excluded.append({"path": name, "reason": "lfs_pointer"})
            continue
        if dest_dir is not None:
            target = os.path.normpath(os.path.join(dest_dir, name))
            if os.path.commonpath([os.path.normcase(target), os.path.normcase(dest_dir)]) != os.path.normcase(dest_dir):
                return Materialization(False, "path_escape")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(blob)
        files.append(
            {
                "path": name,
                "sha256": digest,
                "size": len(blob),
                "object": entry["object"],
            }
        )

    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return Materialization(
        True,
        None,
        files=files,
        excluded=excluded,
        warnings=warnings,
        digest=digest,
        lfs_pointers=lfs,
    )