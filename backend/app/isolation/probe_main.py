"""隔离探针（在受限令牌 worker 进程中运行，仅标准库）。

输入：一个 JSON 规格文件路径（由父进程写入 sandbox）。
输出：一个 JSON 证据文件路径；只记录布尔结果、错误类型与 SHA-256 是否匹配，
绝不复制文件内容/环境变量值，避免 canary 或凭据写入证据。

判定：
- allowed_read：必须可读且 SHA-256 匹配；
- deny_read：必须读取失败；
- deny_write：必须写入失败；
- token_restricted：必须为真（IsTokenRestricted，存在 restricting SID）。
任一不符 → ok=false。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 注意：probe 不导入 ctypes/hashlib（受限令牌下部分 DLL 可能不可加载）；
# 令牌受限性由父进程打开子进程令牌用 IsTokenRestricted 证据化，allowed 文件
# 的 SHA-256 也由父进程复核；这里只记录“可读/不可读/不可写”。


def _check_allowed(entry: dict) -> dict:
    path = Path(entry["path"])
    try:
        data = path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__, "size": None}
    return {"ok": True, "error": None, "size": len(data)}


def _check_deny_read(entry: dict) -> dict:
    path = Path(entry["path"])
    try:
        with open(path, "rb") as handle:
            handle.read(1)
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "denied": True, "error": type(exc).__name__}
    return {"ok": False, "denied": False, "error": None}


def _check_deny_write(entry: dict) -> dict:
    path = Path(entry["path"])
    try:
        path.write_text("x", encoding="utf-8")
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "denied": True, "error": type(exc).__name__}
    return {"ok": False, "denied": False, "error": None}


def _phase(name: str) -> None:
    """Write a bounded, content-free progress marker to the parent-captured stderr."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(f"adll_probe_phase={name}\n")
            sys.stderr.flush()
    except (OSError, ValueError):
        # A closed/redirected stderr must never mask the real probe result.
        return


def main() -> int:
    _phase("start")
    if len(sys.argv) != 3:
        _phase("bad_arguments")
        return 2
    _phase("check_path")
    target = Path(sys.argv[1])
    # Record ancestors the restricted token cannot stat. This is diagnostic
    # only: stat may require FILE_READ_ATTRIBUTES where traversal only needs
    # FILE_TRAVERSE, so a stat failure must not mask the real read attempt.
    for candidate in (target, *target.parents):
        try:
            candidate.stat()
        except OSError as exc:
            _phase(f"stat_denied:{candidate}:{type(exc).__name__}")
    _phase("read_spec")
    spec = json.loads(target.read_text(encoding="utf-8"))
    _phase("run_checks")
    evidence: dict = {
        "token_restricted": None,  # 由父进程打开子进程令牌后填写
        "token_restricted_source": "parent_open_process_token",
        "allowed_read": {},
        "deny_read": {},
        "deny_write": {},
    }
    for entry in spec.get("allowed_read", []):
        evidence["allowed_read"][entry["name"]] = _check_allowed(entry)
    for entry in spec.get("deny_read", []):
        evidence["deny_read"][entry["name"]] = _check_deny_read(entry)
    for entry in spec.get("deny_write", []):
        evidence["deny_write"][entry["name"]] = _check_deny_write(entry)

    checks = [item["ok"] for item in evidence["allowed_read"].values()]
    checks += [item["ok"] for item in evidence["deny_read"].values()]
    checks += [item["ok"] for item in evidence["deny_write"].values()]
    evidence["probe_checks_ok"] = bool(checks) and all(checks)
    evidence["ok"] = evidence["probe_checks_ok"]
    _phase("write_evidence")
    Path(sys.argv[2]).write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    _phase("done")
    return 0 if evidence["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())