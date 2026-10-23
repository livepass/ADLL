"""在既有独立低权限账户（如 CodexSandboxOffline）下运行的隔离探针。

**本批未执行**。由用户/已获授权的本地助手在沙箱账户中运行：
    python -I scripts/account_isolation_probe.py \
      --allow <subset-file> --deny <repo-dir> --deny <db-file> --deny <user-dir> \
      --tcp-host 127.0.0.1 --tcp-port 8765 --out evidence.json

只读取路径存在性/内容并尝试 TCP 连接；不读取/打印任何凭据，不写真实目录。
退出码：0=全部符合预期；3=有不符合；2=参数错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
from pathlib import Path


def current_sid() -> str:
    try:
        output = subprocess.run(
            ["whoami.exe", "/user"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        ).stdout
        for token in output.replace(",", " ").split():
            if token.startswith("S-1-"):
                return token
    except Exception:  # noqa: BLE001
        pass
    return ""


def read_check(path: Path, must_fail: bool) -> dict:
    try:
        data = path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        return {"ok": must_fail, "read": False, "error": type(exc).__name__}
    return {
        "ok": not must_fail,
        "read": True,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write_check(path: Path) -> dict:
    target = path / "adll_probe_write.tmp" if path.is_dir() else path
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


def tcp_check(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=3):
            return {"ok": False, "connected": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "connected": False, "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--deny", action="append", default=[])
    parser.add_argument("--deny-write", action="append", default=[])
    parser.add_argument("--tcp-host", default="")
    parser.add_argument("--tcp-port", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    evidence: dict = {"identity_sid": current_sid(), "allow": {}, "deny": {}, "deny_write": {}}
    for raw in args.allow:
        path = Path(raw)
        evidence["allow"][str(path)] = read_check(path, must_fail=False)
    for raw in args.deny:
        path = Path(raw)
        evidence["deny"][str(path)] = read_check(path, must_fail=True)
    for raw in args.deny_write:
        path = Path(raw)
        evidence["deny_write"][str(path)] = write_check(path)
    if args.tcp_host and args.tcp_port:
        evidence["tcp"] = {
            "target": f"{args.tcp_host}:{args.tcp_port}",
            **tcp_check(args.tcp_host, args.tcp_port),
        }
    checks = []
    for group in ("allow", "deny", "deny_write"):
        checks.extend(item["ok"] for item in evidence[group].values())
    if "tcp" in evidence:
        checks.append(evidence["tcp"]["ok"])
    evidence["ok"] = bool(checks) and all(checks)
    Path(args.out).write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return 0 if evidence["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())