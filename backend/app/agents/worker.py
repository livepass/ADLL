"""受限 Worker AgentAdapter（批 8）：把真实/合成调用放入独立受限进程。

- `self_check()` 只有在真实 OS 探针（受限令牌 + DACL 允许/拒绝 + 写拒绝）全部通过
  时才返回 ok；不存在人工把 ok 设为 true 的配置项。
- `generate()` 每次重新创建 sandbox 并重新探针，失败即 `AdapterDisabled`（零发送）。
- worker 只接收已组装 payload；不持有仓库路径、数据库或审批服务引用。
- 真实传输必须由显式配置启用（`real_transport=True` 且 worker 环境
  `ADLL_WORKER_REAL_TRANSPORT=1`）；默认 fail-closed。本批不做真实调用。
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from ..core.payload import canonical_payload_bytes
from ..isolation.sandbox import IsolationSpec, ProbeResult, Sandbox
from ..isolation.win32 import error_details
from ..models.enums import CancelOutcome
from .base import (
    AdapterCapabilities,
    AgentAdapter,
    BoundaryCheckReport,
    EventSink,
    GenerationRequest,
    GenerationResult,
)
from .dashscope import AdapterCancelled, AdapterDisabled, AdapterResponseError


class WorkerAgentAdapter(AgentAdapter):
    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout: int = 30,
        sandbox_root: str | Path | None = None,
        acl_root: str | Path | None = None,
        deny_read: tuple[str, ...] = (),
        deny_write: tuple[str, ...] = (),
        python_executable: str | None = None,
        synthetic: bool = False,
        real_transport: bool = False,
        worker_principal_sid: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.sandbox_root = Path(sandbox_root) if sandbox_root else None
        self.acl_root = Path(acl_root) if acl_root else None
        self.deny_read = tuple(deny_read)
        self.deny_write = tuple(deny_write)
        self.python_executable = python_executable
        self.synthetic = synthetic
        self.real_transport = real_transport
        self.worker_principal_sid = worker_principal_sid
        # 最近一次 worker job/result（不含凭据；供审计/测试检查序列化面）。
        self.last_job: dict | None = None
        self.last_result: dict | None = None
        self._active: dict[str, Sandbox] = {}
        self._active_lock = threading.Lock()

    # ---- isolation ----

    def _spec(self) -> IsolationSpec:
        return IsolationSpec(
            sandbox_root=self.sandbox_root or Path("."),
            acl_root=self.acl_root,
            deny_read=tuple(Path(p) for p in self.deny_read),
            deny_write=tuple(Path(p) for p in self.deny_write),
            python_executable=self.python_executable,
            process_timeout_seconds=max(30, self.timeout + 10),
        )

    def _probe(self) -> ProbeResult:
        if self.sandbox_root is None:
            return ProbeResult(False, {"error": "sandbox_root_not_configured"}, "config")
        if not self.deny_read and not self.deny_write:
            return ProbeResult(False, {"error": "no_deny_objects_configured"}, "config")
        missing = [p for p in (*self.deny_read, *self.deny_write) if not Path(p).exists()]
        if missing:
            return ProbeResult(
                False, {"error": "deny_object_missing", "count": len(missing)}, "config"
            )
        try:
            with Sandbox(self._spec()) as sandbox:
                return sandbox.probe(sandbox.write_subset({"probe.txt": b"probe"}))
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(False, {"error": type(exc).__name__, "details": error_details(exc)}, type(exc).__name__)

    def self_check(self) -> BoundaryCheckReport:
        result = self._probe()
        return BoundaryCheckReport(
            ok=result.ok,
            details={
                "worker_isolation": "verified" if result.ok else "unverified",
                "evidence": result.evidence,
                "error": result.error,
                "approval": False,
                "tools": False,
            },
        )

    # ---- generation ----

    def generate(
        self, request: GenerationRequest, sink: EventSink | None = None
    ) -> GenerationResult:
        if not isinstance(request.payload, dict):
            raise AdapterResponseError("host-assembled payload required")
        probe = self._probe()
        if not probe.ok:
            # 探针失败 → 不启动 worker，不发送任何数据。
            raise AdapterDisabled("isolation_unverified")
        mode = "synthetic" if self.synthetic else "real"
        env_extra: dict[str, str] = {}
        if mode == "real":
            if not self.real_transport:
                raise AdapterDisabled("real_transport_disabled")
            key = os.environ.get("DASHSCOPE_API_KEY")
            if not key:
                raise AdapterDisabled("DASHSCOPE_API_KEY missing (never logged)")
            # S9 强制门禁：真实传输必须满足可信采集的 OS 网络边界证据。
            # 仅 real_transport + API Key 存在不能绕过；未配置/采集异常/覆盖不足
            # 一律 fail-closed，零外发。合成模式不冒充真实 OS 网络证据。
            from ..services import network_boundary

            evidence = network_boundary.collect_boundary_evidence(
                self.worker_principal_sid
            )
            boundary = network_boundary.evaluate(evidence)
            if not boundary.passed:
                raise AdapterDisabled(
                    f"s9_network_boundary_{boundary.status}:"
                    + ",".join(boundary.reasons)
                )
            env_extra["ADLL_WORKER_REAL_TRANSPORT"] = "1"
            env_extra["DASHSCOPE_API_KEY"] = key
        if sink is not None:
            sink.emit({"type": "start"})
        body_bytes = (
            canonical_payload_bytes(request.payload) if mode == "real" else None
        )
        # S9-2：授权摘要必须来自已持久化 prepared 审计行（request.request_digest），
        # 不得由 adapter 自行生成替代值。真实发送要求两者都提供且一致。
        request_digest = request.request_digest
        if mode == "real":
            # 完整绑定校验：attempt/authorization/receiver/request_digest 缺一即零外发。
            # adapter 不得自造 attempt_id 或授权摘要；一切取自 prepared 审计行。
            if not isinstance(request.attempt_id, str) or not request.attempt_id:
                raise AdapterDisabled("attempt_id_missing")
            if request.authorization_id is None:
                raise AdapterDisabled("authorization_id_missing")
            if not isinstance(request.receiver, str) or not request.receiver:
                raise AdapterDisabled("receiver_missing")
            if request.receiver != self.endpoint:
                # 实际端点必须与 prepared 行的 receiver 一致，否则视为跨任务替换。
                raise AdapterDisabled("receiver_mismatch")
            if not isinstance(request_digest, str) or not request_digest:
                raise AdapterDisabled("request_digest_missing")
            # 用不可变请求字节核对授权摘要：重算仅为比对，不当作新的授权摘要。
            recomputed = hashlib.sha256(body_bytes).hexdigest()
            if recomputed != request_digest:
                raise AdapterDisabled("request_digest_mismatch")
        job = {
            "mode": mode,
            "synthetic_allowed": self.synthetic,
            "endpoint": self.endpoint,
            "model": self.model,
            "payload": request.payload,
            "requirement": request.requirement_text,
            "timeout": self.timeout,
        }
        if body_bytes is not None:
            # 直接把持久化授权摘要传给 worker；worker 发送前对不可变字节复核。
            job["request_digest"] = request_digest
            # attempt_id 完整绑定到 worker job，worker 不自行生成替代 attempt_id。
            job["attempt_id"] = request.attempt_id
            job["authorization_id"] = request.authorization_id
        key = str(request.execution_id or request.idempotency_key or id(request))
        with Sandbox(self._spec()) as sandbox:
            with self._active_lock:
                self._active[key] = sandbox
            try:
                result = sandbox.run(job, env_extra=env_extra, body_bytes=body_bytes)
            finally:
                with self._active_lock:
                    self._active.pop(key, None)
        self.last_job = job
        self.last_result = result
        if not result.get("ok"):
            error = str(result.get("error", "worker_failed"))
            if error == "worker_timeout":
                from .dashscope import AdapterTimeout

                raise AdapterTimeout("worker timed out")
            if error.startswith("worker_no_result") or error == "worker_terminated":
                raise AdapterCancelled(
                    "worker terminated", sent=bool(result.get("sent"))
                )
            raise AdapterResponseError(error, sent=bool(result.get("sent")))
        response = result.get("response")
        if not isinstance(response, dict):
            raise AdapterResponseError("response_not_object")
        stop_reason = response.get("stop_reason")
        if stop_reason == "max_tokens":
            raise AdapterResponseError("truncated:max_tokens")
        if stop_reason != "end_turn":
            raise AdapterResponseError("stop_reason_invalid")
        content = response.get("content")
        if not isinstance(content, list):
            raise AdapterResponseError("content_missing")
        parts = []
        for block in content:
            if not isinstance(block, dict):
                raise AdapterResponseError("content_block_invalid")
            if block.get("type") == "text":
                value = block.get("text")
                if not isinstance(value, str):
                    raise AdapterResponseError("text_not_string")
                parts.append(value)
        text = "".join(parts)
        if not text.strip():
            raise AdapterResponseError("empty_content")
        usage = response.get("usage")
        if self.synthetic:
            # 合成结果不是服务商用量依据；不得标记 actual。
            usage_value = {}
            usage_basis = "unavailable"
        elif (
            isinstance(usage, dict)
            and isinstance(usage.get("input_tokens"), int)
            and isinstance(usage.get("output_tokens"), int)
        ):
            usage_value = usage
            usage_basis = "actual"
        else:
            usage_value = {}
            usage_basis = "unavailable"
        if sink is not None:
            sink.emit({"type": "delta", "text": text})
        return GenerationResult(
            text=text,
            citations=[],
            usage=usage_value,
            usage_basis=usage_basis,
            # 真实账单不可得；不得由 usage 推断金额。
            cost={"amount": None, "currency": None, "basis": "unknown"},
            terminal_status="completed",
            tool_call_log=[],
            send_evidence={
                "transport": "worker-synthetic" if self.synthetic else "worker-real",
                "sent": bool(result.get("sent")),
                "confirmed": True,
                "response_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            },
        )

    def cancel(self, execution_id: str) -> CancelOutcome:
        with self._active_lock:
            sandbox = self._active.get(str(execution_id))
        if sandbox is None or not sandbox.cancel():
            return CancelOutcome.NOT_CANCELLED
        return CancelOutcome.CANCELLED

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            {
                "provider": "synthetic_worker" if self.synthetic else "dashscope_worker",
                "endpoint": self.endpoint,
                "model": self.model,
                "tools": False,
                "network": not self.synthetic,
                "real_model": not self.synthetic,
                "approval": False,
                "isolation": "restricted_token_dacl_job",
            }
        )
