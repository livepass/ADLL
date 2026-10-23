# ADR-C1 / C2 / C3 —— 存储、ORM 与 Git 访问 技术选型决策登记（adr-c1-c2-c3-decision-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-20
**状态**: **Accepted（人工技术裁定，2026-10-20）**。
用户正式批准以下 ADR 技术方向；本文据用户授权登记人工裁定，并**如实列出尚未通过的
实现验证项**——候选方案的**实际行为不得标记为已验证**（验证须待实现期 + 相应测试/验收）。

## 1. 决策登记（逐项）

| ADR | 决策 | 依据/配套 | 与 C4 的衔接 |
|---|---|---|---|
| **ADR-C1（SQLite）** | V1.1 本地持久化采用 **SQLite** | 单用户本地；任务/需求版本/方案/审批/审计的不可变与唯一约束落地 | 与 C4 无关（存储层） |
| **ADR-C2（SQLAlchemy 2.x + Alembic）** | ORM 用 **SQLAlchemy 2.x**，迁移用 **Alembic** | 事务、唯一索引、`BEGIN IMMEDIATE`/WAL、CAS 支撑幂等与并发收敛（plan §32–36） | — |
| **ADR-C3（Git CLI 子进程）** | Git 访问用**子进程 `git` CLI + `git archive`**，固定完整 Commit SHA | 遵守 FV-0 已验证的 Git 安全与归档边界（见 [adr-c3-git-access-decision-draft.md](./adr-c3-git-access-decision-draft.md) §5） | 供 C4（候选 C）后端组装快照用 |
| **ADR-C4（Messages API + AgentAdapter）** | **维持已批准**（候选 C），**不重新选择 Claude Agent SDK** | [adr-c4-ai-access-decision-draft.md](./adr-c4-ai-access-decision-draft.md)（Accepted） | 本表仅作状态备忘 |

## 2. 尚未通过的实现验证项（不得标为已验证；实现期覆盖）

| # | 未验证项 | 验证方式（待实现） |
|---|---|---|
| 1 | SQLite **并发写/CAS** 语义（唯一索引落败、WAL 锁、`BEGIN IMMEDIATE` 序号分配）在真实并发下 | 后端 pytest 并发用例 + 唯一索引冲突路径 |
| 2 | SQLAlchemy 2.x + SQLite dialect 的**方言行为**（JSON 列、事务、`sqlite3` 驱动选择） | 迁移 + 单测 |
| 3 | Git CLI 子进程在**真实目标仓库**（非合成 fixture）上的行为与错误面 | 实现期 S 系列 + 探针（research R2） |
| 4 | **SHA-256 对象仓库**、大仓/特殊文件系统（LFS/submodule/符号链接/`export-ignore`） | 沿用 FV-0 合成矩阵外扩真实样例 |
| 5 | Git 子进程的**超时/取消/进程树**终止边界（子进程逃逸） | 取消语义 + Job/进程纳管测试 |
| 6 | Alembic 在 SQLite 上的**迁移幂等/重复执行** | 迁移演练 |

> 说明：FV-0 已核实的 7 项 Git 行为（见 ADR-C3 草案 §5）为**合成样本范围**的已核实事实，
> 继续有效但不扩展到上述未验证项。

## 3. 明确不构成

- 本文件只登记**技术方向裁定**；不标记上述任一候选的运行时行为为「已验证」。
- 不修改 spec.md、宪章、AGENTS.md、CLAUDE.md、ADLL-Knowledge 或历史实验原始证据。
- 本文件未改变 C4 的 Accepted 记录（仅备忘）。