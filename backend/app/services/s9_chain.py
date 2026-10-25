"""S9-3A 合成链路：Host → Launcher IPC → Egress Relay → Synthetic Provider →
签名收据 → Host 审计。

**离线合成**：本模块不创建 VM、不联网、不读取真实 Key、不调用百炼。
Synthetic Provider 是进程内的确定性实现，只用于验证链路的**结构与证据传递**，
不代表真实传输，也不得据此宣称生产已验收。

信任边界（与 contracts/s9-ipc-and-evidence.md 对应）：

- Host 持有审批数据库，从**已持久化的 prepared 行**构造授权请求 + 签名收据。
- Launcher **不读取审批数据库**；它只验证宿主签名收据 + 实际字节摘要，并用自己的
  持久化 replay store 做单次处理。身份（TokenUser/Job）在真实部署由 S9-1 门禁证明，
  本合成链路不做也不冒充。
- Egress 只接受**固定 Messages 路径**，不提供 CONNECT/SOCKS/任意 URL 转发。
- 任一步失败 → 不自动重发；已进入发送阶段的失败按 `possibly_sent` 如实上报。
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from ..core.payload import canonical_payload_bytes
from ..models.s9_replay import S9ReplayGuard
from . import receipts
from .receipts import HostAuthorizationReceipt, SendReceipt

# 出口唯一允许的上游路径（固定 Messages POST）。
ALLOWED_EGRESS_PATH = "/apps/anthropic/v1/messages"
ALLOWED_EGRESS_HOST = "dashscope.aliyuncs.com"
DEFAULT_POLICY_VERSION = "s9-3a-synthetic-v1"


class ChainDenied(Exception):
    """链路拒绝（未发送）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class AuthorizationRequest:
    """宿主编排出的授权请求（不含任何凭据）。"""

    attempt_id: str
    authorization_id: int
    receiver: str
    request_digest: str
    body: bytes
    model: str
    timeout_ms: int
    nonce: str
    policy_version: str
    host_receipt: HostAuthorizationReceipt | None = None
    # Launcher 在转发前签发；Egress 用它认证调用者（问题 B）。
    launcher_auth: receipts.LauncherAuth | None = None


@dataclass
class ChainOutcome:
    """链路结果（如实反映发送事实）。"""

    attempt_id: str
    phase: str  # confirmed_sent | possibly_sent | not_sent
    receipt: SendReceipt | None = None
    error_code: str | None = None
    launcher_evidence: dict = field(default_factory=dict)
    egress_evidence: dict = field(default_factory=dict)
    cancelled: bool = False


# ---- 持久化防重放（每个消费方各自拥有，不共享审批库） ----


class ReplayStore:
    """单次处理登记；`register` 返回 True 表示首次见到该 attempt。"""

    def register(self, consumer: str, attempt_id: str, nonce: str | None = None) -> bool:
        raise NotImplementedError


class DbReplayStore(ReplayStore):
    """基于数据库的 replay store（重启后仍生效）。

    注意：这是链路自己的登记表，**不是**审批数据库；Launcher 用它只记录
    「我处理过哪些 attempt」，无法据此读取审批记录。
    """

    def __init__(self, db) -> None:
        self.db = db

    def register(self, consumer: str, attempt_id: str, nonce: str | None = None) -> bool:
        row = S9ReplayGuard(consumer=consumer, attempt_id=attempt_id, nonce=nonce)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return False
        return True


# ---- Synthetic Provider（进程内、确定性、不联网） ----


@dataclass
class SyntheticProvider:
    """确定性合成 Provider：只回显请求摘要，绝不发起网络请求。"""

    fail_mode: str = "ok"  # ok | timeout | connection_reset

    def send(self, body: bytes, *, timeout_ms: int) -> dict:
        digest = hashlib.sha256(body).hexdigest()
        if self.fail_mode == "timeout":
            raise TimeoutError("synthetic provider timeout")
        if self.fail_mode == "connection_reset":
            raise ConnectionError("synthetic provider connection reset")
        return {
            "provider": "synthetic",
            "provider_request_id": "syn-" + digest[:16],
            "http_status": 200,
            "raw_body": (
                '{"id":"syn-'
                + digest[:16]
                + '","stop_reason":"end_turn","content":[{"type":"text",'
                '"text":"SYNTHETIC_EGRESS_OK"}]}'
            ).encode("utf-8"),
        }


# ---- Egress Relay ----


@dataclass
class EgressRelay:
    """应用层受控出口：只接受固定 Messages POST，签发结构化收据。

    放行条件是**两道独立凭证**（问题 B）：
    1. 调用者认证：`launcher_auth` 用已登记的 Launcher 密钥验签（未配置即拒绝）；
    2. 宿主授权：`host_receipt` 用宿主公钥验签，且 approved/未过期/字段一致。
    仅凭 receiver + request_digest + policy_version 不足以放行。
    """

    signing_key: bytes
    key_id: str
    policy_version: str = DEFAULT_POLICY_VERSION
    provider: SyntheticProvider = field(default_factory=SyntheticProvider)
    replay: ReplayStore | None = None
    receipt_ttl_seconds: int = 300
    # 调用者（Launcher）公钥集合：key_id → key；空表示未配置 → fail-closed。
    launcher_keys: dict[str, bytes] = field(default_factory=dict)
    # 宿主公钥：用于验证 host_receipt；None 表示未配置 → fail-closed。
    host_public_key: bytes | None = None
    allowed_policy_versions: tuple[str, ...] = (DEFAULT_POLICY_VERSION,)

    def forward(
        self,
        request: AuthorizationRequest,
        *,
        now: datetime | None = None,
    ) -> SendReceipt:
        # 1) 固定端点 + 固定路径：不具备通用代理能力。
        if not _is_fixed_messages_endpoint(request.receiver):
            raise ChainDenied("egress_endpoint_not_allowed")
        # 2) 调用者认证：必须来自被授权的 Launcher，而不是任意本地进程。
        self._authenticate_caller(request, now=now)
        # 3) 宿主授权凭证：Egress 独立验证，不依赖 Launcher 的结论。
        self._verify_host_grant(request, now=now)
        # 4) 实际字节摘要必须与授权摘要一致（三方核对第二跳）。
        actual = hashlib.sha256(request.body).hexdigest()
        if actual != request.request_digest:
            raise ChainDenied("egress_body_digest_mismatch")
        if request.policy_version != self.policy_version:
            raise ChainDenied("egress_policy_version_mismatch")
        # 5) 持久化单次处理：重复 attempt 直接拒绝，不转发第二次。
        if self.replay is not None and not self.replay.register(
            "egress", request.attempt_id, request.nonce
        ):
            raise ChainDenied("egress_replayed_attempt")

        # 6) 进入发送阶段：此后任何异常都不得断言「未发送」。
        try:
            response = self.provider.send(request.body, timeout_ms=request.timeout_ms)
        except TimeoutError:
            return self._receipt(request, actual, "possibly_sent", None, None, "timeout")
        except ConnectionError:
            return self._receipt(
                request, actual, "possibly_sent", None, None, "connection_reset"
            )

        raw = response["raw_body"]
        return self._receipt(
            request,
            actual,
            "confirmed_sent",
            int(response["http_status"]),
            hashlib.sha256(raw).hexdigest(),
            None,
            provider_request_id=response.get("provider_request_id"),
        )

    def _authenticate_caller(
        self, request: AuthorizationRequest, *, now: datetime | None
    ) -> None:
        if not self.launcher_keys:
            # 未登记任何 Launcher 密钥 → 不发放，绝不降级为「无认证放行」。
            raise ChainDenied("egress_caller_auth_not_configured")
        auth = request.launcher_auth
        if auth is None:
            raise ChainDenied("launcher_auth_missing")
        key = self.launcher_keys.get(auth.key_id)
        if key is None:
            raise ChainDenied("launcher_key_unknown")
        verification = receipts.verify_launcher_auth(
            auth,
            key=key,
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            nonce=request.nonce,
            now=now,
        )
        if not verification.ok:
            raise ChainDenied(f"launcher_auth_{verification.code}")

    def _verify_host_grant(
        self, request: AuthorizationRequest, *, now: datetime | None
    ) -> None:
        if self.host_public_key is None:
            raise ChainDenied("egress_host_key_not_configured")
        if request.host_receipt is None:
            raise ChainDenied("egress_host_receipt_missing")
        actual = hashlib.sha256(request.body).hexdigest()
        verification = receipts.verify_host_receipt_against_request(
            request.host_receipt,
            key=self.host_public_key,
            attempt_id=request.attempt_id,
            authorization_id=request.authorization_id,
            receiver=request.receiver,
            request_digest=request.request_digest,
            body_sha256=actual,
            now=now,
            allowed_policy_versions=self.allowed_policy_versions,
        )
        if not verification.ok:
            raise ChainDenied(f"egress_host_receipt_{verification.code}")

    def _receipt(
        self,
        request: AuthorizationRequest,
        actual: str,
        phase: str,
        http_status: int | None,
        raw_sha256: str | None,
        error_code: str | None,
        *,
        provider_request_id: str | None = None,
    ) -> SendReceipt:
        receipt = receipts.issue_send_receipt(
            attempt_id=request.attempt_id,
            authorization_id=request.authorization_id,
            receiver=request.receiver,
            request_digest=request.request_digest,
            actual_body_sha256=actual,
            terminal_phase=phase,
            http_status=http_status,
            raw_response_sha256=raw_sha256,
            policy_version=self.policy_version,
            key_id=self.key_id,
            key=self.signing_key,
            provider_request_id=provider_request_id,
            ttl_seconds=self.receipt_ttl_seconds,
        )
        return receipt


def _is_fixed_messages_endpoint(receiver: str) -> bool:
    """只接受固定上游 host + 固定 Messages 路径；不接受任意 URL/代理。"""
    if not isinstance(receiver, str):
        return False
    prefix = f"https://{ALLOWED_EGRESS_HOST}"
    if not receiver.startswith(prefix):
        return False
    return receiver[len(prefix):] == ALLOWED_EGRESS_PATH


# ---- 传输层：进程内 / 独立进程 IPC ----


class ChainTransport:
    """Launcher → Egress 的传输抽象。

    默认 `InProcessTransport` 保持既有行为（同一进程内同步调用）；
    `ProcessTransport` 用 `multiprocessing.Pipe` 把请求交给**独立子进程**中的
    Egress 处理，验证跨进程边界下的字节/收据一致性与防重放。

    两者都不联网：Egress 侧只调用进程内 `SyntheticProvider`。
    """

    def forward(self, request: AuthorizationRequest, *, now: datetime | None = None) -> SendReceipt:
        raise NotImplementedError


@dataclass
class InProcessTransport(ChainTransport):
    """进程内直调（默认；合成测试快路径）。"""

    egress: EgressRelay

    def forward(self, request: AuthorizationRequest, *, now: datetime | None = None) -> SendReceipt:
        return self.egress.forward(request, now=now)


@dataclass
class ProcessTransport(ChainTransport):
    """同机**独立子进程** IPC（`multiprocessing.Pipe`）。

    子进程内重建 EgressRelay（自己的 DB session / replay store），因此：
    - 请求字节与授权摘要跨进程传输后仍由出口侧独立重算；
    - 重放登记由子进程写入同一数据库，重启/多进程下仍生效；
    - 主进程被杀时子进程可被 terminate，不遗留发送。
    """

    # Egress 自己的 replay 库（独立文件）：子进程**不打开审批数据库**（问题 D）。
    egress_replay_url: str = ""
    egress_signing_key: bytes = b""
    egress_key_id: str = ""
    policy_version: str = DEFAULT_POLICY_VERSION
    provider_fail_mode: str = "ok"
    timeout_seconds: float = 60.0
    # 子进程 Egress 需要这两组公钥来认证调用者与验证宿主授权（问题 B）。
    launcher_keys: dict[str, bytes] = field(default_factory=dict)
    host_public_key: bytes | None = None
    # 证据：最近一次转发的子进程 PID / 它在自己的库里看到的表（问题 D）。
    last_child_pid: int | None = field(default=None, init=False, repr=False)
    last_child_tables: tuple[str, ...] = field(default=(), init=False, repr=False)

    def forward(self, request: AuthorizationRequest, *, now: datetime | None = None) -> SendReceipt:
        if not self.egress_replay_url:
            raise ChainDenied("egress_replay_store_not_configured")
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        config = {
            "replay_url": self.egress_replay_url,
            "signing_key": self.egress_signing_key,
            "key_id": self.egress_key_id,
            "policy_version": self.policy_version,
            "fail_mode": self.provider_fail_mode,
            "launcher_keys": dict(self.launcher_keys),
            "host_public_key": self.host_public_key,
        }
        process = ctx.Process(
            target=_egress_process_main,
            args=(child_conn, config, _request_to_wire(request)),
            daemon=True,
        )
        process.start()
        child_conn.close()
        try:
            if not parent_conn.poll(self.timeout_seconds):
                # 超时：终止子进程，不重发；由调用方按 possibly_sent 处理。
                process.terminate()
                process.join(10)
                raise TimeoutError("egress process timeout")
            message = parent_conn.recv()
        finally:
            parent_conn.close()
            if process.is_alive():
                process.join(10)
        if message.get("denied"):
            raise ChainDenied(message.get("code", "egress_denied"))
        if message.get("error"):
            raise RuntimeError(f"egress_process_error:{message['error']}")
        self.last_child_pid = message.get("pid")
        self.last_child_tables = tuple(message.get("tables") or ())
        return SendReceipt.from_dict(message["receipt"])


def _request_to_wire(request: AuthorizationRequest) -> dict:
    return {
        "attempt_id": request.attempt_id,
        "authorization_id": request.authorization_id,
        "receiver": request.receiver,
        "request_digest": request.request_digest,
        "body": request.body,
        "model": request.model,
        "timeout_ms": request.timeout_ms,
        "nonce": request.nonce,
        "policy_version": request.policy_version,
        "host_receipt": request.host_receipt.to_dict() if request.host_receipt else None,
        "launcher_auth": request.launcher_auth.to_dict() if request.launcher_auth else None,
    }


def _request_from_wire(data: dict) -> AuthorizationRequest:
    host = data.get("host_receipt")
    launcher_auth = data.get("launcher_auth")
    return AuthorizationRequest(
        attempt_id=data["attempt_id"],
        authorization_id=int(data["authorization_id"]),
        receiver=data["receiver"],
        request_digest=data["request_digest"],
        body=data["body"],
        model=data["model"],
        timeout_ms=int(data["timeout_ms"]),
        nonce=data["nonce"],
        policy_version=data["policy_version"],
        host_receipt=HostAuthorizationReceipt(**host) if host else None,
        launcher_auth=receipts.LauncherAuth(**launcher_auth) if launcher_auth else None,
    )


def _egress_process_main(conn, config: dict, request_wire: dict) -> None:
    """子进程入口（模块级，spawn 可 pickle）。

    子进程只打开**自己的 replay 库**（`replay_url`），并只创建 replay 表；
    它不持有审批数据库路径，因此结构上无法读取审批记录（问题 D）。
    回传 `pid` 与 `tables` 作为可核验证据。
    """
    import os as _os

    from sqlalchemy import inspect as _inspect

    from ..db import Database

    pid = _os.getpid()
    database = Database(config["replay_url"])
    # 只建 replay 表，避免把完整审批 schema 复制进 Egress 的库。
    S9ReplayGuard.__table__.create(database.engine, checkfirst=True)
    tables = tuple(sorted(_inspect(database.engine).get_table_names()))
    db = database.session()
    try:
        egress = EgressRelay(
            signing_key=config["signing_key"],
            key_id=config["key_id"],
            policy_version=config["policy_version"],
            provider=SyntheticProvider(fail_mode=config["fail_mode"]),
            replay=DbReplayStore(db),
            launcher_keys=config.get("launcher_keys") or {},
            host_public_key=config.get("host_public_key"),
        )
        try:
            receipt = egress.forward(_request_from_wire(request_wire))
            conn.send({"receipt": receipt.to_dict(), "pid": pid, "tables": list(tables)})
        except ChainDenied as exc:
            conn.send({"denied": True, "code": exc.code, "pid": pid, "tables": list(tables)})
        except Exception as exc:  # noqa: BLE001 — 子进程异常如实回传
            conn.send({"error": type(exc).__name__, "pid": pid, "tables": list(tables)})
    finally:
        try:
            conn.close()
        finally:
            db.close()


# ---- Launcher ----


@dataclass
class Launcher:
    """Worker VM 内的受保护启动器（合成版）：不读取审批数据库。"""

    host_public_key: bytes
    allowed_policy_versions: tuple[str, ...] = (DEFAULT_POLICY_VERSION,)
    replay: ReplayStore | None = None
    # 调用者密钥：用于向 Egress 证明「我是被授权的 Launcher」（问题 B）。
    launcher_key: bytes | None = None
    launcher_key_id: str = "launcher-k1"
    launcher_auth_ttl_seconds: int = 120

    def dispatch(
        self,
        request: AuthorizationRequest,
        egress: EgressRelay | ChainTransport,
        *,
        now: datetime | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChainOutcome:
        # 1) 可信宿主授权凭证：验签 + 与实际请求字段逐一比对（无审批库可查）。
        if request.host_receipt is None:
            raise ChainDenied("host_receipt_missing")
        actual = hashlib.sha256(request.body).hexdigest()
        check = receipts.verify_host_receipt_against_request(
            request.host_receipt,
            key=self.host_public_key,
            attempt_id=request.attempt_id,
            authorization_id=request.authorization_id,
            receiver=request.receiver,
            request_digest=request.request_digest,
            body_sha256=actual,
            now=now,
            allowed_policy_versions=self.allowed_policy_versions,
        )
        if not check.ok:
            raise ChainDenied(f"host_receipt_{check.code}")

        # 2) 取消（转发前）：确认未写出，可如实记 not_sent。
        if cancel_check is not None and cancel_check():
            return ChainOutcome(
                attempt_id=request.attempt_id,
                phase="not_sent",
                error_code="cancelled_before_send",
                cancelled=True,
                launcher_evidence={"body_sha256": actual, "stage": "cancelled_pre_send"},
            )

        # 3) 持久化单次处理：同一 attempt 只放行一次（跨任务替换在此被拒）。
        if self.replay is not None and not self.replay.register(
            "launcher", request.attempt_id, request.nonce
        ):
            raise ChainDenied("launcher_replayed_attempt")

        # 4) 交给固定出口（进程内或独立进程）。语义：拒绝发生在转发前 → not_sent；
        #    转发阶段异常 → possibly_sent；**任何情况都不自动重发**。
        #    转发前先签发调用者凭证，使 Egress 能认证本次调用来自被授权的 Launcher。
        if self.launcher_key is None:
            raise ChainDenied("launcher_key_not_configured")
        request.launcher_auth = receipts.issue_launcher_auth(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            nonce=request.nonce,
            key_id=self.launcher_key_id,
            key=self.launcher_key,
            ttl_seconds=self.launcher_auth_ttl_seconds,
        )
        transport = (
            egress if isinstance(egress, ChainTransport) else InProcessTransport(egress)
        )
        try:
            receipt = transport.forward(request, now=now)
        except ChainDenied as exc:
            return ChainOutcome(
                attempt_id=request.attempt_id,
                phase="not_sent",
                error_code=exc.code,
                launcher_evidence={"body_sha256": actual, "stage": "egress_denied"},
            )
        except Exception as exc:  # noqa: BLE001 — 转发阶段未知异常按可能已发送
            return ChainOutcome(
                attempt_id=request.attempt_id,
                phase="possibly_sent",
                error_code=type(exc).__name__,
                launcher_evidence={"body_sha256": actual, "stage": "egress_exception"},
            )

        # 5) 取消（转发后）：请求已可能写出，不可撤回，如实标记。
        cancelled_after = cancel_check is not None and cancel_check()
        return ChainOutcome(
            attempt_id=request.attempt_id,
            phase=receipt.terminal_phase,
            receipt=receipt,
            cancelled=cancelled_after,
            error_code="cancelled_after_send" if cancelled_after else None,
            launcher_evidence={
                "body_sha256": actual,
                "stage": "cancelled_post_send" if cancelled_after else "forwarded",
            },
            egress_evidence={
                "provider_request_id": receipt.provider_request_id,
                "http_status": receipt.http_status,
                "policy_version": receipt.policy_version,
            },
        )


# ---- Host ----


@dataclass
class HostGateway:
    """宿主侧：从 prepared 行构造请求 + 收据，并在收到收据后核验落账。"""

    signing_key: bytes
    key_id: str
    policy_version: str = DEFAULT_POLICY_VERSION
    receipt_ttl_seconds: int = 300

    def build_request(
        self,
        *,
        prepared,
        body: bytes,
        model: str,
        timeout_ms: int = 30000,
        attempt_id: str | None = None,
        nonce: str | None = None,
    ) -> AuthorizationRequest:
        """**只从已持久化的 prepared 行**取 attempt/authorization/receiver/digest。"""
        attempt = attempt_id or prepared.attempt_id
        if not attempt:
            raise ChainDenied("prepared_attempt_id_missing")
        if not prepared.request_digest:
            raise ChainDenied("prepared_request_digest_missing")
        actual = hashlib.sha256(body).hexdigest()
        if actual != prepared.request_digest:
            raise ChainDenied("body_digest_mismatch")
        host_receipt = receipts.issue_host_receipt(
            attempt_id=attempt,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            policy_version=self.policy_version,
            key_id=self.key_id,
            key=self.signing_key,
            ttl_seconds=self.receipt_ttl_seconds,
        )
        return AuthorizationRequest(
            attempt_id=attempt,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            body=body,
            model=model,
            timeout_ms=timeout_ms,
            nonce=nonce or uuid.uuid4().hex,
            policy_version=self.policy_version,
            host_receipt=host_receipt,
        )

    def build_request_from_db(
        self,
        db,
        *,
        attempt_id: str,
        body: bytes,
        model: str,
        timeout_ms: int = 30000,
        nonce: str | None = None,
        now: datetime | None = None,
    ) -> AuthorizationRequest:
        """严格版：attempt 必须命中已持久化 prepared 行，且授权仍有效。

        三重校验，任一失败即拒绝签发宿主授权收据：
        1. `SendAuditRecord(attempt_id, phase="prepared")` 存在；
        2. 其 `authorization_id` 对应的 `OutboundAuthorization` 存在；
        3. 该授权**当前有效**（未撤销、已批准、未过期）且 receiver 与 prepared 行一致。

        授权可能在 prepared 之后被撤销，故此处按调用时刻重新判定（fail-closed）。
        """
        from ..models.outbound import OutboundAuthorization, SendAuditRecord
        from . import outbound as outbound_service

        prepared = (
            db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id, phase="prepared")
            .one_or_none()
        )
        if prepared is None:
            raise ChainDenied("prepared_row_missing")

        auth = db.get(OutboundAuthorization, prepared.authorization_id)
        if auth is None:
            raise ChainDenied("authorization_missing")
        reason = outbound_service.inactive_reason(auth, now)
        if reason is not None:
            # revoked / not_approved / expired / no_authorization
            raise ChainDenied(f"authorization_{reason}")
        if auth.receiver != prepared.receiver:
            raise ChainDenied("authorization_receiver_mismatch")
        if not auth.task_id or not auth.baseline_id:
            raise ChainDenied("authorization_unverifiable")

        return self.build_request(
            prepared=prepared,
            body=body,
            model=model,
            timeout_ms=timeout_ms,
            attempt_id=attempt_id,
            nonce=nonce,
        )

    def settle(self, db, *, outcome: ChainOutcome, prepared, egress_key: bytes):
        """把链路结果落账：核验收据 → 唯一终态；已有终态则追加迟到证据。

        返回 (verification, appended_late_evidence)。
        """
        from . import outbound

        if outcome.receipt is None:
            # 无收据：只能如实记 not_sent / possibly_sent，不伪造 confirmed。
            if (
                outcome.phase in ("not_sent", "possibly_sent")
                and not receipts.has_terminal(db, outcome.attempt_id)
            ):
                outbound.finish_attempt(
                    db, outcome.attempt_id, phase=outcome.phase,
                    error_code=outcome.error_code or "chain_no_receipt",
                )
            return receipts.ReceiptVerification(False, outcome.error_code or "no_receipt"), False

        verification = receipts.verify_send_receipt(
            outcome.receipt,
            key=egress_key,
            prepared=prepared,
            expected_policy_version=self.policy_version,
        )
        if not verification.ok:
            if not receipts.has_terminal(db, outcome.attempt_id):
                outbound.finish_attempt(
                    db, outcome.attempt_id, phase="possibly_sent",
                    error_code=f"receipt_{verification.code}",
                )
            return verification, False

        if receipts.has_terminal(db, outcome.attempt_id):
            # 已有终态 → 迟到收据只追加证据，不写第二终态、不自动 verified。
            late = receipts.record_late_receipt(
                db, receipt=outcome.receipt, key=egress_key, prepared=prepared
            )
            return late, True

        # 契约 §6.2：撤销与签发的时序边界。
        # 宿主依「撤销时间 vs 收据签发时间」判定，不依赖 Egress 自证。
        from ..models.outbound import OutboundAuthorization

        auth = db.get(OutboundAuthorization, prepared.authorization_id)
        race = _revocation_race(auth, outcome.receipt)
        # fail-closed：以下情况都无法证明「签发时授权有效」，一律不得升格
        # confirmed_sent。缺授权记录（authorization_missing）与签发时间不可解析
        # （issued_at_invalid）同样必须拒绝，不能因为没有撤销记录就默认放行。
        if race in ("revoked_before_issue", "authorization_missing", "issued_at_invalid"):
            if not receipts.has_terminal(db, outcome.attempt_id):
                outbound.finish_attempt(
                    db, outcome.attempt_id, phase="possibly_sent", error_code=race
                )
            _record_evidence(db, outcome, "revocation_race", race)
            return receipts.ReceiptVerification(False, race), False
        if race == "revoked_after_issue":
            # 签发时授权仍有效，之后才被撤销：收据有效，但留证以便审计追溯。
            _record_evidence(db, outcome, "revocation_after_issue", "recorded")

        outbound.finish_attempt(
            db, outcome.attempt_id, phase=outcome.receipt.terminal_phase
        )
        return verification, False


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _revocation_race(auth, receipt: SendReceipt) -> str | None:
    """契约 §6.2：授权撤销与收据签发的时间边界判定。

    - `None`：未撤销，或无法判定（授权缺失时返回 authorization_missing）。
    - `revoked_before_issue`：撤销时间 ≤ 签发时间 → 收据虽签名有效，但签发落在撤销之后/同时，
      不得升格 `confirmed_sent`。
    - `revoked_after_issue`：签发时仍有效、之后才撤销 → 收据有效，仅留证。

    这是**竞态窗口的显式声明**：收据 TTL 内发生的撤销无法阻断已签发的发送，
    但必须可按时间戳判定归属，而不是事后静默接受。
    """
    if auth is None:
        return "authorization_missing"
    revoked = getattr(auth, "revoked_at", None)
    if revoked is None:
        return None
    issued = receipts._parse_iso(receipt.issued_at)
    if issued is None:
        return "issued_at_invalid"
    if _naive_utc(revoked) <= _naive_utc(issued):
        return "revoked_before_issue"
    return "revoked_after_issue"


def _record_evidence(db, outcome: ChainOutcome, kind: str, verification: str) -> None:
    """追加撤销竞态证据；重复写入按唯一索引幂等忽略。"""
    if outcome.receipt is None:
        return
    try:
        receipts.append_receipt_evidence(
            db,
            attempt_id=outcome.attempt_id,
            kind=kind,
            receipt=outcome.receipt.to_dict(),
            verification=verification,
        )
    except IntegrityError:
        db.rollback()


def reconcile_pending(db) -> int:
    """链路层重启恢复入口：把只剩 `prepared`、无终态的 attempt 补记 `possibly_sent`。

    复用既有 `generation_service.reconcile_orphan_attempts`（不改其语义）：
    - 不补 `confirmed_sent`（无法证明已收到响应）；
    - 不补 `not_sent`（无法证明未写出）；
    - 已有终态的 attempt 不重复终结。
    """
    from .generation_service import reconcile_orphan_attempts

    return reconcile_orphan_attempts(db)


def run_synthetic_chain(
    db,
    *,
    prepared,
    payload: dict,
    model: str,
    host: HostGateway,
    launcher: Launcher,
    egress: EgressRelay,
):
    """一次性跑通合成链路（测试/联调用）。不联网、不读真实 Key。"""
    body = canonical_payload_bytes(payload)
    request = host.build_request(prepared=prepared, body=body, model=model)
    outcome = launcher.dispatch(request, egress)
    verification, appended = host.settle(
        db, outcome=outcome, prepared=prepared, egress_key=egress.signing_key
    )
    return request, outcome, verification, appended
