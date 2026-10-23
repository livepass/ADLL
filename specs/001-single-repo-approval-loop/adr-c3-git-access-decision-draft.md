# ADR-C3：Git 访问方式选型 —— 正式决策草案（adr-c3-git-access-decision-draft.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**状态**: **Accepted（人工技术裁定，2026-10-20）**。
用户正式批准 ADR-C3 技术方向：Git 访问采用子进程 Git CLI + `git archive`，固定完整
Commit SHA，遵守 FV-0 已验证的 Git 安全与归档边界。登记依据用户授权，非 Agent 自批。
（实现未验证项见 [adr-c1-c2-c3-decision-record.md](./adr-c1-c2-c3-decision-record.md) §2。）
**Date**: 2026-10-18
**依据**: [research.md](./research.md) R6/ADR-C3（候选格局与 P1-02
修正）、FV-0 实测发现回填（2026-10-18）、
[fv0-acceptance-record.md](./fv0-acceptance-record.md)、
[fv0-v22-acceptance-record.md](./fv0-v22-acceptance-record.md)
（P2～P5 合成样本范围内验证通过）。

## 1. 背景（Context）

ADLL 需要对目标仓库做**只读快照与完整性证据**生成（R3）：快照生成、
归档名清单、与 `git ls-tree` 的逐项差异对照、特殊内容（LFS 指针、
submodule gitlink、符号链接、export-ignore/export-subst）语义处理。
Git 访问层是 ADR 红线内的**重要技术选型**（AGENTS.md §2：须 ADR 记录
依据与取舍并获人工批准）。

历史修正（P1-02）：此前文档误写"GitPython 依赖 libgit2"。已核实事实：
GitPython 内部以子进程方式调用系统 git CLI；libgit2 绑定是 pygit2。

## 2. 决策驱动因素

1. **行为可控可证**：快照/归档行为必须可由离线合成用例实测并留证
   （FV-0/FV-1.1 回归已走通该路径）。
2. **依赖面最小**：Windows 11 本地单用户；避免原生编译依赖。
3. **安全参数处理**：禁 shell 拼接、参数数组构造、防注入（R2/R5）。
4. **证据完整性**：归档作证据时的"零写入、不跟随链接、LFS 不 smudge"
   语义须可陈述（R3.1/FR-045）。
5. **失败可降级**：不预设任一方案一定满足全部要求，保留替换面
   （AgentAdapter 同理适用于 Git 访问的封装边界）。

## 3. 候选与取舍

| 候选 | 依赖关系 | 优势 | 劣势 | 结论（草案） |
|---|---|---|---|---|
| **子进程调用 `git` CLI** | 系统 git 可执行文件；无 Python 库依赖 | 行为与系统 git 同源；零第三方库；FV-0 全部必需行为本机实测可达成 | 安全参数构造责任在实现层（参数数组、禁 shell 拼接）；输出解析自理 | **推荐（本草案决策）** |
| GitPython | **同样依赖系统 git CLI**（不用 libgit2） | 封装便利 | 相对自管子进程仅封装便利，安全参数处理责任不变；多一层依赖 | 备选（行为同源，结论共享） |
| pygit2 | libgit2 绑定（原生编译依赖） | 底层对象访问 | Windows 原生构建/轮子兼容面需验证；行为面与 git CLI 有差异风险 | 放弃（除非未来 FV 证明必要） |
| Dulwich | 纯 Python | 无原生依赖 | archive/对象读取场景行为一致性未验证 | 备选（暂无引入必要） |

## 4. 决策（草案，待人工批准生效）

**采用子进程 Git CLI + `git archive` 作为 Git 访问层推荐方案。**

配套默认（与 R3.1 一致）：
- 快照生成默认 `git archive`（对原仓库 `.git` 零写入，FV-0 实测）；
  `git worktree` 仅作授权备选（会写 `$GIT_DIR/worktrees/`）。
- 全部 git 调用：参数数组构造、禁 shell 拼接、逐调用受控环境
 （FV-0 已验证的净化模式可复用）。

## 5. 依据（已核实行为事实，FV-0 + V2.2 回归）

| # | 已核实行为事实 | 对实现的影响 |
|---|---|---|
| 1 | `git archive` 在 SHA-1 与 SHA-256 仓库均正常导出 | 覆盖两种对象格式；无需 libgit2 |
| 2 | `git archive` 对原仓库 `.git` 零写入；`git worktree add` 写 `$GIT_DIR/worktrees/` | 默认 archive，worktree 仅授权备选 |
| 3 | archive 对 gitlink 路径输出空目录占位条目（`mods/child/`，size 0），子模块内容不含 | 归档名清单解析须做"目录占位/gitlink"归一化 |
| 4 | `export-ignore` 按目录属性递归剔除子树；子文件 `check-attr` 返回 unspecified | 差异对照须查祖先目录属性（`ea_parent_set` 语义） |
| 5 | `export-subst` 在归档内容中正常展开 | 归档 vs `git show` 内容不同属预期，比对器须区分 |
| 6 | LFS 指针原样导出、不 smudge（配置净化 + `GIT_LFS_SKIP_SMUDGE=1`） | 归档可安全作证据；「LFS 内容未包含」语义可陈述 |
| 7 | 符号链接以链接条目保留、目标字符串可三方核对；逃逸链接目标**内容**「未验证」 | 归档解析须拒绝跟随链接；逃逸内容不升格表述 |

以上均在合成样本范围内验证（结论适用范围见
[fv0-v22-acceptance-record.md](./fv0-v22-acceptance-record.md) §4）。
GitPython 与子进程行为同源，上表对两者同样适用；取舍仅剩封装便利性。

## 6. 后果（Consequences）

1. 实现层自担安全参数构造与输出解析；须以单元测试覆盖参数注入面
   （宪章原则 II：核心逻辑正常+失败双场景）。
2. 运行环境依赖系统 git（版本记录进环境清单；行为敏感点采用前重核）。
3. 未来若需 libgit2 级行为（如无 git 二进制环境），须重走 ADR 并以
   FV 证明必要性；不得静默替换。
4. 本草案批准后：research.md ADR-C3 候选段以本 ADR 为准更新标注，
   **不删除**历史修正说明与 FV-0 回填表（追加状态行）。

## 7. 未决事项（Open）

1. **P1 三条异常分支未实测**（Git 命令异常/证据缺失/判定器错误熔断）
   ——不影响本选型结论（属 harness 层），但列入 AI 调用前门禁
   （[p1-exception-branch-gate-plan.md](./p1-exception-branch-gate-plan.md)）。
2. 真实大仓/特殊文件系统行为未验证（合成样本范围限制）。
3. Dulwich 在 archive 场景的对照评估仅文档级，无实测。

## 8. 批准（待人工签署）

| 项 | 内容 |
|---|---|
| 草案编制 | Agent（2026-10-18），依据用户裁定 5 |
| **人工终选批准** | **已签署（用户 2026-10-20 首批开发授权：ADR-C3 子进程 Git CLI + git archive 方案批准）**——登记依据用户授权，非 Agent 自批 |
| 批准日期 | 2026-10-20 |
| 备注 | 实现未验证项（真实仓库/超时取消/大仓特殊格式等）见 [adr-c1-c2-c3-decision-record.md](./adr-c1-c2-c3-decision-record.md) §2 |
