# S9 详细技术规划与部署预检 — 交付汇总

**日期**：2026-10-24　**基线**：`5c4aa56`（= 本机 HEAD，工作区干净）
**边界**：只读调查 + 规划 + 新建草案；未创建 VM/账户、未装组件、未改 ACL/防火墙、
未读 Key、未真实请求、未改 ADLL-Knowledge、未 Commit/Push。

## 1. 现有规格与代码核对结论

已核对：spec.md、plan.md、tasks.md、contracts/agent-adapter.md、AGENTS.md、
本地宪章（v1.2.0 RATIFIED）、win32.py、sandbox.py、worker.py、factory.py、
generation_service.py、outbound.py、network_boundary.py。

**代码现状与架构决策文档 §2 完全一致**，关键缺口确认如下：

| 缺口 | 现状 | 新架构要求 |
|---|---|---|
| 独立 TokenUser | `CreateRestrictedToken` 不更换 TokenUser；Worker 仍是父账户 SID | Launcher `LogonUserW` + 专用账户主令牌 |
| 挂起创建 | `CreateProcessAsUserW` 无 `CREATE_SUSPENDED` | 挂起创建 + 身份复核 + Job 纳管后再恢复 |
| Job 失败回收 | `job.assign` 失败分支仅关闭句柄，未 terminate 进程树 | 补 terminate + 等待 |
| 审计绑定 | `GenerationRequest` 无 `attempt_id`/`request_digest`，adapter 自行重算 | 直接传入，发送前对不可变字节复核 |
| 采集器 | 无进程身份/策略版本/可信拒绝观测；覆盖字段 False | 补身份、策略版本、拒绝观测、有效期 |
| 网络 | 旧 host block_all+allow_dashscope 已裁定 NO-GO | 独立 VM + 专用网络 + 固定出口 |

**未修改任何已批准需求，未删除历史记录**；新架构差异全部落在新增草案文档。

## 2. 产出文档（均为新建 DRAFT，不覆盖已批准文件）

| 文档 | 内容 |
|---|---|
| `s9-detailed-plan.md` | S9 详细技术规划（部署边界/IPC/身份/绑定/出口/网络/凭据/证据/矩阵） |
| `contracts/s9-ipc-and-evidence.md` | IPC 与安全证据接口契约（新增，不改 agent-adapter.md） |
| `s9-phased-tasks.md` | 分阶段任务与验收标准（新增，不改 tasks.md） |
| `s9-deployment-feasibility.md` | 部署位置预检与 GO/CONDITIONAL-GO/NO-GO |
| `s9-risk-acceptance-rollback-matrix.md` | 风险、验收、回滚矩阵 |

## 3. 部署预检结论

- 本机：Windows 11 家庭版 21H2，Hyper-V 角色 Disabled，空闲内存仅 2.3 GiB，
  CPU 虚拟化字段 False（与 HypervisorPresent=True 矛盾，属 WMI 误报）。
  **本机 NO-GO（当前版本与资源）**，不假设一定能在本机跑。
- 独立主机 / 云 VM：**CONDITIONAL GO**，需进一步确认资源/许可/网络/成本。
- 本轮不决定最终宿主。

## 4. 验收状态（GitHub CI）

- 最新 run `40051212654`（`5c4aa56`）conclusion **success**（backend + frontend）。
- 基线 cb3a40e 的 pytest 实测：**282 passed / 3 skipped**（架构决策 §8 已核实）；
  `5c4aa56` 仅追加文档、测试集未变。
- **本机尚未验证的 S9 实际安全边界**：独立 TokenUser、挂起创建、Job 失败回收、
  VM 默认拒绝网络、固定出口、拒绝观测——全部未在真实 OS 环境验证，
  CI success 不等于身份/网络隔离通过。

## 5. 实施前提（待人工批准后才能进入）

1. 批准本组四份规划/契约/任务/风险文档。
2. 选定部署宿主（本机升级 / 独立主机 / 云 VM）。
3. 批准 VM/网络/出口、账户与登录权、启动器、专用 ACL/策略/审计、凭据注入。
4. 真实 OS 验收与首次真实百炼调用（合成内容）单独授权。

## 6. 需要人工批准的操作

见 `s9-risk-acceptance-rollback-matrix.md` §4；任何 VM/账户/防火墙/凭据/真实调用
操作均未执行，等待人工审批。
