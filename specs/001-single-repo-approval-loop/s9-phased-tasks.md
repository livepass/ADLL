# S9 分阶段实施任务草案

**日期**：2026-10-24　**状态**：DRAFT（待审批；不改已批准 tasks.md）
**上位**：[s9-detailed-plan.md](./s9-detailed-plan.md)、[s9-ipc-and-evidence.md](./contracts/s9-ipc-and-evidence.md)

不重复开发现有 Mock、审批与发送授权模块；只覆盖 S9 身份 + 网络隔离改造。

## Phase S9-0：架构与契约固化（本批可完成）

- [ ] 批准 S9 详细规划、IPC 契约、分阶段任务与部署可行性（本组文档）。
- [ ] 确定部署宿主（本机 / 独立主机 / 云 VM），记录资源与许可结论。

## Phase S9-1：身份与进程隔离改造（win32 / sandbox / launcher）

- [ ] `win32.py`：`LogonUserW(LOGON32_LOGON_BATCH)` 获专用账户主令牌，验证 TokenUser。
- [ ] `win32.py`：`CreateProcessAsUserW` 增加 `CREATE_SUSPENDED`，最小环境 + 句柄白名单。
- [ ] `win32.py`：恢复前查询子进程真实 TokenUser/PID/创建时间/程序摘要/受限状态。
- [ ] `win32.py`：`job.assign` 失败分支补 terminate + 等待，不遗留未纳管进程。
- [ ] `sandbox.py`：输入/输出权限分离（程序、授权输入、审计收据只读，输出独立可写）。
- [ ] 验收：受限 Worker 的 TokenUser 匹配批准 SID；挂起创建 + 身份复核 + Job 纳管 + 进程树回收。

## Phase S9-2：审计与请求体直接绑定（outbound / generation / agent）

- [ ] `GenerationRequest` 增加 `attempt_id`、`request_digest`，`_run_body` 直接传入。
- [ ] `worker.py`/launcher 发送前用 `request_digest` 复核不可变请求体（不再自行重算）。
- [ ] 收据绑定同一 `attempt_id`，唯一终态。
- [ ] 验收：摘要篡改、收据重放/跨任务替换均被拒；attempt/authorization/receiver/request_digest 一致。

## Phase S9-3：固定出口与网络默认拒绝（egress relay + VM 网络）

- [ ] 部署专用网络 + Worker VM（默认拒绝）+ 固定出口（仅固定 Messages POST）。
- [ ] TLS 校验证书、禁重定向、不重编码、不自动重试、单次请求。
- [ ] IPv4/IPv6/回环/代理/UDP/子进程/服务代发边界覆盖与验证。
- [ ] 验收：非授权目的地拒绝观测（5157 关联）；授权通道可达；无任意转发。

## Phase S9-4：证据核验与门禁接线（network_boundary / verification）

- [ ] `network_boundary` 采集器补进程身份、策略版本、可信拒绝观测、有效期。
- [ ] 发送前/发送后证据分离核验；生产拒绝手填布尔值、synthetic 证据。
- [ ] 验收：缺任何发送前证据 → 零外发；发送后收据/原始响应摘要/唯一终态齐全。

## Phase S9-5：实机验收与回滚演练

- [ ] 实机测试矩阵（身份/网络/证据/异常）全量；回滚演练（关发送→回收→断网→保存→撤资源）。
- [ ] 首次真实请求单独审批（合成业务内容）。

## 依赖顺序

S9-1 → S9-2 → S9-3 → S9-4 → S9-5；S9-3 的 VM/网络部署在部署宿主确定并单独批准后执行。
