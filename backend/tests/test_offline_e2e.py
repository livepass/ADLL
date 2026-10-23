"""离线端到端验收：登录 → 关联 → 任务/需求 → 授权 → Mock 生成 → 核验 → 批准 → 失效 → 撤销。

全程 ADLL_TESTING=1、Mock 合成、无外部网络、无真实源码外发。
"""
from __future__ import annotations

import time

from tests.helpers import csrf_headers, login_client, make_repo

TERMINAL = {"completed", "failed", "timeout", "cancelled", "late_result_discarded"}


def test_offline_end_to_end_mock_workflow(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),), testing=True)
    client, csrf = login_client(app)

    health = client.get("/api/health").json()
    assert health["testing"] is True and health["real_ai_enabled"] is False

    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    assert linked["needs_decision"] is False
    assert len(linked["baseline"]["commit_sha"]) in {40, 64}
    assert linked["baseline"]["object_format"] == "sha1"

    task = client.post(
        "/api/tasks",
        json={
            "repository_id": linked["repository"]["id"],
            "baseline_id": linked["baseline"]["id"],
            "title": "离线验收",
        },
        headers=csrf_headers(csrf, "e2e-task"),
    ).json()["task"]
    requirement = client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "离线验收需求"},
        headers=csrf_headers(csrf, "e2e-req"),
    ).json()["requirement_version"]

    authorization = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "dashscope", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "e2e-auth"),
    ).json()["authorization"]

    started = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": authorization["id"]},
        headers=csrf_headers(csrf, "e2e-gen"),
    )
    assert started.status_code == 202, started.text
    execution_id = started.json()["execution_id"]
    assert started.json()["snapshot"]["files"] == ["a.txt"]

    detail = {}
    for _ in range(300):
        detail = client.get(f"/api/generations/{execution_id}").json()
        if detail["execution"]["status"] in TERMINAL:
            break
        time.sleep(0.02)
    assert detail["execution"]["status"] == "completed"
    assert detail["execution"]["provider"] == "mock"  # 合成标识，不冒充真实服务商
    assert detail["verification"]["status"] == "verified"
    assert detail["verification"]["evidence_sufficiency"]["sufficient"] is True
    assert detail["proposal"] is not None

    # 用量/费用双维度：用量有依据；费用未返回金额时不编造。
    assert detail["execution"]["usage"]["input_tokens"] == 10
    assert detail["execution"]["usage_basis"] == "actual"
    assert detail["execution"]["cost"]["amount"] is None

    audit = client.get(f"/api/generations/{execution_id}/send-audit").json()["audits"]
    assert len(audit) == 1
    assert audit[0]["payload_manifest"]["source"] == [
        {
            "path": "a.txt",
            "sha256": audit[0]["payload_manifest"]["source"][0]["sha256"],
        }
    ]
    assert audit[0]["payload_manifest"]["tool_return"] == []
    assert audit[0]["authorization_id"] == authorization["id"]

    proposals = client.get(f"/api/tasks/{task['id']}/proposals").json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["requirement_version_id"] == requirement["id"]
    assert proposals[0]["approval_effective"] is False

    approved = client.post(
        f"/api/tasks/{task['id']}/proposals/1/approve",
        json={"reason": "离线验收"},
        headers=csrf_headers(csrf, "e2e-approve"),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval"]["commit_sha"] == linked["baseline"]["commit_sha"]
    assert approved.json()["approval"]["proposal_content_hash"] == proposals[0]["content_hash"]

    approvals = client.get(f"/api/tasks/{task['id']}/approvals").json()["approvals"]
    assert len(approvals) == 1 and approvals[0]["effective"] is True

    duplicate = client.post(
        f"/api/tasks/{task['id']}/proposals/1/approve",
        json={"reason": "重复"},
        headers=csrf_headers(csrf, "e2e-approve-2"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "approval_exists"

    # 新需求版本 → 旧批准失效（不继承）。
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "变更后的需求"},
        headers=csrf_headers(csrf, "e2e-req-2"),
    )
    approvals = client.get(f"/api/tasks/{task['id']}/approvals").json()["approvals"]
    assert approvals[0]["effective"] is False

    # 撤销授权 → 再发起生成被拒且零发送（不产生新执行）。
    client.post(
        f"/api/outbound-authorizations/{authorization['id']}/revoke",
        headers=csrf_headers(csrf, "e2e-revoke"),
    )
    denied = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": authorization["id"]},
        headers=csrf_headers(csrf, "e2e-gen-2"),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "outbound_denied"