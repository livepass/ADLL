"""生成编排（T031/T033/T034）：出站门禁 → 发送前审计 → 执行 → 适配器 → 核验 → 方案版本。

取消语义：
- 取消仅在**发送前**生效 → `cancelled`（未发送），审计记 `not_sent`；
- 若请求已发出，取消不能撤回已发数据 → `not_cancelled`，迟到结果写入
  LateResultRecord（discard），不生成方案、不覆盖版本、不自动批准；
- 已终态 → `already_finished`。
- 重启后遗留 running 执行 → failed（restart_incomplete），不判 verified。

接收方不再由调用方传入：从适配器 `capabilities()` 的实际端点读取，避免
“用授权记录自证接收方”的循环校验。
"""
from __future__ import annotations

import hashlib
import threading

from sqlalchemy.exc import IntegrityError

from ..agents.base import GenerationRequest
from ..agents.dashscope import (
    AdapterCancelled,
    AdapterDisabled,
    AdapterResponseError,
    AdapterTimeout,
)
from ..models.base import utcnow
from ..models.generation import GenerationExecution, VerificationAttempt
from ..models.late_result import LateResultRecord
from ..models.outbound import OutboundAuthorization
from ..models.proposal import ProposalVersion
from . import outbound, outbound_pipeline, task_service, verification

TERMINAL = {"completed", "failed", "timeout", "cancelled", "late_result_discarded"}

_CANCEL_EVENTS: dict[int, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()
_ACTIVE_ADAPTERS: dict[int, object] = {}


class GenerationBlocked(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GenerationFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def actual_receiver(adapter) -> str:
    """Read the endpoint the adapter will really use; no caller-supplied value."""
    declares = getattr(adapter.capabilities(), "declares", {}) or {}
    endpoint = declares.get("endpoint")
    if not isinstance(endpoint, str) or "://" not in endpoint:
        raise GenerationBlocked("receiver_unverifiable")
    return endpoint


def _isolation_snapshot(adapter, *, testing: bool) -> dict:
    check = adapter.self_check()
    isolation = {"ok": bool(check.ok), "details": dict(check.details or {})}
    if not testing and not check.ok:
        raise GenerationBlocked("isolation_unverified")
    return isolation


def _finish(db, execution, status: str, reason: str | None) -> None:
    execution.status = status
    execution.failure_reason = reason
    execution.finished_at = utcnow()
    db.commit()


def _create_running(db, task, auth, requirement_id: int, testing: bool) -> GenerationExecution:
    execution = GenerationExecution(
        task_id=task.id,
        baseline_id=task.baseline_id,
        requirement_version_id=requirement_id,
        status="running",
        provider="mock" if testing else "dashscope",
        outbound_authorization_id=auth.id,
    )
    db.add(execution)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GenerationBlocked("active_execution_exists") from None
    db.refresh(execution)
    return execution


def _record_attempt(
    db,
    auth,
    *,
    task_id: int,
    baseline_id: int,
    execution_id: str,
    prepared,
) -> str:
    return outbound.begin_attempt(
        db,
        auth,
        task_id=task_id,
        baseline_id=baseline_id,
        execution_id=execution_id,
        receiver=prepared.receiver,
        manifest=prepared.payload_manifest,
        request_digest=prepared.request_digest,
        payload_digest=prepared.request_digest,
    )


def _finalize(db, attempt_id: str, phase: str, error_code: str | None = None) -> None:
    outbound.finish_attempt(db, attempt_id, phase=phase, error_code=error_code)


def _run_body(
    db,
    execution: GenerationExecution,
    prepared,
    adapter,
    *,
    auth_id: int,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    requirement_id: int,
    task_id: int,
    baseline_id: int,
    snapshot_digest: str | None,
    snapshot_manifest: list[dict] | None,
    isolation: dict,
    testing: bool,
    cancel_event: threading.Event | None,
):
    auth = db.get(OutboundAuthorization, auth_id)

    if cancel_event is not None and cancel_event.is_set():
        # 取消发生在发送前：仍留下一条可追溯的 not_sent 尝试记录。
        try:
            attempt_id = _record_attempt(
                db,
                auth,
                task_id=task_id,
                baseline_id=baseline_id,
                execution_id=str(execution.id),
                prepared=prepared,
            )
            _finalize(db, attempt_id, "not_sent", "cancelled_before_send")
        except PermissionError as exc:
            from .approval_service import record_security_event

            record_security_event(
                db, "send_audit_denied", {"task_id": task_id, "reason": str(exc)}
            )
        execution.status = "cancelled"
        execution.cancel_outcome = "cancelled"
        execution.finished_at = utcnow()
        db.commit()
        return None, None

    try:
        attempt_id = _record_attempt(
            db,
            auth,
            task_id=task_id,
            baseline_id=baseline_id,
            execution_id=str(execution.id),
            prepared=prepared,
        )
    except PermissionError as exc:
        from .approval_service import record_security_event

        record_security_event(
            db, "send_audit_denied", {"task_id": task_id, "reason": str(exc)}
        )
        raise GenerationBlocked("audit_unavailable") from None

    request = GenerationRequest(
        subset_path=None,
        requirement_text=requirement_text,
        feedback_texts=feedback_texts,
        send_manifest=prepared.payload_manifest,
        payload=prepared.payload,
        execution_id=execution.id,
    )
    try:
        result = adapter.generate(request)
    except AdapterCancelled as exc:
        if cancel_event is not None and cancel_event.is_set():
            # worker 被终止：sent 标记决定是否已发出；未发出才可如实称 cancelled。
            _finalize(db, attempt_id, "possibly_sent" if exc.sent else "not_sent", "cancelled")
            execution.status = "cancelled"
            execution.cancel_outcome = "not_cancelled" if exc.sent else "cancelled"
            execution.finished_at = utcnow()
            db.commit()
            return None, None
        _finalize(db, attempt_id, "possibly_sent" if exc.sent else "not_sent", "adapter_cancelled")
        _finish(db, execution, "failed", "adapter_cancelled")
        return None, None
    except AdapterTimeout:
        _finalize(db, attempt_id, "possibly_sent", "timeout")
        _finish(db, execution, "timeout", "timeout")
        return None, None
    except (AdapterDisabled, AdapterResponseError) as exc:
        sent = bool(getattr(exc, "sent", True))
        _finalize(db, attempt_id, "possibly_sent" if sent else "not_sent", str(exc))
        _finish(db, execution, "failed", str(exc))
        return None, None
    except Exception as exc:  # noqa: BLE001
        # 未知异常发生在调用期间：不能断言未发送，按“可能已发送”记录。
        _finalize(db, attempt_id, "possibly_sent", type(exc).__name__)
        _finish(db, execution, "failed", type(exc).__name__)
        return None, None

    _finalize(db, attempt_id, "confirmed_sent")
    send_phase = "confirmed_sent"

    if cancel_event is not None and cancel_event.is_set():
        # 请求已发出，无法撤回；迟到结果丢弃记录，不生成方案
        db.add(
            LateResultRecord(
                execution_id=execution.id,
                digest=hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
                disposition="discard",
            )
        )
        execution.status = "cancelled"
        execution.cancel_outcome = "not_cancelled"
        execution.finished_at = utcnow()
        db.commit()
        return None, None

    execution.status = "completed"
    execution.usage = result.usage
    execution.usage_basis = result.usage_basis
    execution.cost = result.cost
    execution.finished_at = utcnow()
    db.commit()

    outcome = verification.verify(
        prepared=prepared,
        source_items=source_items,
        snapshot_digest=snapshot_digest,
        snapshot_manifest=snapshot_manifest,
        isolation=isolation,
        send_phase=send_phase,
        result_text=result.text,
        result_evidence=dict(getattr(result, "send_evidence", {}) or {}),
        testing=testing,
    )
    attempt_no = (
        db.query(VerificationAttempt).filter_by(execution_id=execution.id).count() + 1
    )
    record = VerificationAttempt(
        execution_id=execution.id,
        attempt_no=attempt_no,
        status=outcome.status,
        isolation_evidence=outcome.isolation,
        evidence_sufficiency=outcome.evidence_sufficiency,
        coverage_note=outcome.coverage_note,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    proposal = None
    if outcome.status == "verified" and outcome.sufficient:
        last = (
            db.query(ProposalVersion)
            .filter_by(task_id=task_id)
            .order_by(ProposalVersion.seq.desc())
            .first()
        )
        seq = (last.seq if last else 0) + 1
        proposal = ProposalVersion(
            task_id=task_id,
            seq=seq,
            requirement_version_id=requirement_id,
            baseline_id=baseline_id,
            execution_id=execution.id,
            content=result.text,
            content_hash=hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
    return record, proposal


def _prepare(
    db,
    task,
    auth,
    adapter,
    *,
    requirement_text,
    feedback_texts,
    source_items,
    model,
    testing,
    expected_digest=None,
):
    receiver = actual_receiver(adapter)
    prepared = outbound_pipeline.prepare(
        task=task,
        auth=auth,
        receiver=receiver,
        requirement_text=requirement_text,
        feedback_texts=feedback_texts,
        source_items=source_items,
        model=model,
    )
    # 隔离未通过时先拒绝（连“是否需要预览”都不必问）。
    isolation = _isolation_snapshot(adapter, testing=testing)
    # 生产发送必须由操作者确认过预览摘要；测试模式按合成证据运行。
    if not testing:
        if not expected_digest:
            raise GenerationBlocked("preview_required")
        if expected_digest != prepared.request_digest:
            raise GenerationBlocked("preview_digest_mismatch")
    return prepared, isolation


def start(
    db,
    task,
    auth,
    *,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    model: str,
    adapter,
    snapshot_digest: str | None = None,
    snapshot_manifest: list[dict] | None = None,
    preview_digest: str | None = None,
    testing: bool = False,
):
    prepared, isolation = _prepare(
        db,
        task,
        auth,
        adapter,
        requirement_text=requirement_text,
        feedback_texts=feedback_texts,
        source_items=source_items,
        model=model,
        testing=testing,
        expected_digest=preview_digest,
    )
    requirement = task_service.current_requirement(db, task)
    if requirement is None:
        raise GenerationBlocked("no_requirement")
    execution = _create_running(db, task, auth, requirement.id, testing)
    verification_record, proposal = _run_body(
        db,
        execution,
        prepared,
        adapter,
        auth_id=auth.id,
        requirement_text=requirement_text,
        feedback_texts=feedback_texts,
        source_items=source_items,
        requirement_id=requirement.id,
        task_id=task.id,
        baseline_id=task.baseline_id,
        snapshot_digest=snapshot_digest,
        snapshot_manifest=snapshot_manifest,
        isolation=isolation,
        testing=testing,
        cancel_event=None,
    )
    if execution.status == "timeout":
        raise GenerationFailed("timeout")
    if execution.status == "failed":
        raise GenerationFailed(execution.failure_reason or "adapter_failed")
    return execution, verification_record, proposal


def _async_worker(
    db_factory,
    execution_id: int,
    prepared,
    adapter,
    auth_id: int,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    requirement_id: int,
    task_id: int,
    baseline_id: int,
    snapshot_digest: str | None,
    snapshot_manifest: list[dict] | None,
    isolation: dict,
    testing: bool,
    cancel_event: threading.Event,
) -> None:
    db = db_factory()
    try:
        execution = db.get(GenerationExecution, execution_id)
        if execution is None:
            return
        _run_body(
            db,
            execution,
            prepared,
            adapter,
            auth_id=auth_id,
            requirement_text=requirement_text,
            feedback_texts=feedback_texts,
            source_items=source_items,
            requirement_id=requirement_id,
            task_id=task_id,
            baseline_id=baseline_id,
            snapshot_digest=snapshot_digest,
            snapshot_manifest=snapshot_manifest,
            isolation=isolation,
            testing=testing,
            cancel_event=cancel_event,
        )
    except Exception:  # noqa: BLE001
        db.rollback()
        try:
            execution = db.get(GenerationExecution, execution_id)
            if execution is not None and execution.status == "running":
                _finish(db, execution, "failed", "worker_error")
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        with _CANCEL_LOCK:
            _CANCEL_EVENTS.pop(execution_id, None)
            _ACTIVE_ADAPTERS.pop(execution_id, None)
        db.close()


def start_async(
    db,
    db_factory,
    task,
    auth,
    *,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    model: str,
    adapter,
    snapshot_digest: str | None = None,
    snapshot_manifest: list[dict] | None = None,
    preview_digest: str | None = None,
    testing: bool = False,
) -> int:
    prepared, isolation = _prepare(
        db,
        task,
        auth,
        adapter,
        requirement_text=requirement_text,
        feedback_texts=feedback_texts,
        source_items=source_items,
        model=model,
        testing=testing,
        expected_digest=preview_digest,
    )
    requirement = task_service.current_requirement(db, task)
    if requirement is None:
        raise GenerationBlocked("no_requirement")
    execution = _create_running(db, task, auth, requirement.id, testing)
    event = threading.Event()
    with _CANCEL_LOCK:
        _CANCEL_EVENTS[execution.id] = event
        _ACTIVE_ADAPTERS[execution.id] = adapter
    thread = threading.Thread(
        target=_async_worker,
        args=(
            db_factory,
            execution.id,
            prepared,
            adapter,
            auth.id,
            requirement_text,
            feedback_texts,
            source_items,
            requirement.id,
            task.id,
            task.baseline_id,
            snapshot_digest,
            snapshot_manifest,
            isolation,
            testing,
            event,
        ),
        daemon=True,
    )
    thread.start()
    return execution.id


def request_cancel(db, execution_id: int) -> str | None:
    execution = db.get(GenerationExecution, execution_id)
    if execution is None:
        return None
    if execution.status in TERMINAL:
        if execution.cancel_outcome is None:
            execution.cancel_outcome = "already_finished"
            db.commit()
        return "already_finished"
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(execution_id)
        adapter = _ACTIVE_ADAPTERS.get(execution_id)
    execution.cancel_requested = True
    if event is not None:
        event.set()
    if adapter is not None:
        try:
            adapter.cancel(str(execution_id))
        except Exception:  # noqa: BLE001 — 取消尽力而为，最终结果由工作线程记录
            pass
    db.commit()
    # 仅表示“已受理”；最终结果由工作线程写入（cancelled / not_cancelled）
    return "cancel_requested"


def reconcile_after_restart(db) -> int:
    """重启恢复：遗留 running → failed（restart_incomplete），不判 verified。"""
    running = db.query(GenerationExecution).filter_by(status="running").all()
    for execution in running:
        execution.status = "failed"
        execution.failure_reason = "restart_incomplete"
        execution.finished_at = utcnow()
    if running:
        db.commit()
    return len(running)
