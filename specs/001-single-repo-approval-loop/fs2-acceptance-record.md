# FS2 —— P1 熔断异常分支离线验证 人工验收记录（fs2-acceptance-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**对象**: FS2 四场景（G1 Git 命令异常 / G2a 证据缺失 / G2b 证据空文件 /
G3 判定器错误）离线验证；执行日 2026-10-18；
执行根 `%TEMP%/adll-fv0/run-20261018-fs2`（批次 + `g1/`、`g2a/`、
`g2b/`、`g3/` 四个独立场景子根）
**验收人**: 用户（人工裁定，2026-10-18）
**验收结论**: **FS2 = PASS（函数级验证）**——V2.2 原有熔断函数的
三类异常路径（Git 命令异常、证据缺失或空文件、判定器错误）在本次
合成测试中有效。
**验证边界（强制保留）**: 本次通过**不代表** V2.2 **整脚本**全部
异常调用路径已经验证（见 §2、§6、§7）。
**性质**: 人工验收记录（**引用**既有证据，不修改、不覆盖任何原始
证据与脚本；结论适用范围见 §6，不得外推）。

## 1. 人工裁定登记（2026-10-18，逐条）

1. 接受 G1、G2a、G2b、G3 四个独立离线场景的执行结果。
2. **FS2 结论：PASS（函数级验证）**。确认 V2.2 原有熔断函数的
   Git 命令异常、证据缺失或空文件、判定器错误三类异常路径在本次
   合成测试中有效。
3. 必须保留验证边界：本次通过**不代表** V2.2 整脚本全部异常调用
   路径已经验证。
4. **Gate-G-P1**：正式同意解除 Gate-G-P1 对 **FV-1 准备工作**的
   阻断，并登记 FS2 的四场景证据引用、验证级别和遗留风险
   （§5）。**不得将本次门禁解除解释为 FV-1 自动获批。**
5. **G3 的 90 返回码**在后续文档中明确标记为 **classifier_error
   （判定器错误）**，避免与「未归类差异数量」混淆；
   **原始证据保持不变**。

## 2. 实现载体与验证级别（读验收结论前必读）

| 项 | 实测内容 |
|---|---|
| 载体脚本 | `%TEMP%/adll-fv0/run-20261018-fs2/run-p1-fs2.sh`（新建独立自检脚本；**未修改** run-fv0-v2.2.sh 及任何既有脚本） |
| 来源门禁 | 运行前校验 V2.2 哈希：actual = expected = `f00f9cb5c61c9f455e6d743ca2ace1cc6cb76a63296362981c357b18e7336ca1`（`00-fs2-v22-hashgate.txt`，四场景一致） |
| 逻辑来源 | 从哈希门禁通过的 V2.2 **字节级提取** 12 个函数（awk 名称锚定）：`log`、`assert_in_root`、`fail_stop`、`cell_verdict`、`require_evid`、`ginit`、`gcommit`、`gadd`、`tree_names`、`arch_names`、`ea_parent_set`、`do_diff`，写入 `fs2-functions.inc` 后 source 执行 |
| 提取一致性 | `fs2-functions.inc` sha256 = `d60e16235f6b53d815ca5527f25ea7ed7ed6637f4fd26ffa7b848a7bbfe7f9f4`（4704 字节），**四场景完全相同**（`99-fs2-batch-final.txt`） |
| **验证级别** | **function-level（字节级提取复用真实熔断函数；NOT whole-script injection）**——每场景摘要行原文含此限定 |

**由此确定的能力边界**：

- ✅ 已证：被提取的这 12 个函数在本次注入条件下**真实执行**（非行为
  相似的独立模拟），熔断路径与收尾行为真实发生。
- ❌ 未证：**整脚本注入**（把异常注入 run-fv0-v2.2.sh 本体并整脚本
  运行）；V2.2 中未被提取的其余代码路径（各格命令序列、门禁、收尾
  编排的其他调用点）未在本次覆盖范围内。
- 因此「P1 三类异常分支在 V2.2 **整脚本**中同样生效」属**合理推断**，
  **未经本次实测**，不得表述为已证事实（AGENTS.md §5.4）。

## 3. 逐场景验收（原始摘要行逐字引用）

四场景通用事实：`VERIFICATION_LEVEL = function-level（字节级提取；
非整脚本注入——验收结论按此限定）`；
`STOP_RULE = §8-2/P1: 保留证据、停止后续格、不自行修复重试；
剩余测试格未执行`；`REAL-REPO = pass(ADLL 仓库 status 前后逐字节一致)`；
`CLEANUP = skipped(保留 fixtures/evidence；清理须单独授权)`；
`EXIT_CODE = 3`。每场景仅执行一次。

| 场景 | 注入方式 | 前置步骤（必须全绿） | 原始判定行（原文） | STOP 行（原文） | 后续步骤 | 收尾 | 裁定 |
|---|---|---|---|---|---|---|---|
| **G1** Git 命令异常 | `git -C <fixture> show HEAD:fs2-nonexistent-file.txt` 经 `\|\| cell_verdict` 路径 | PRE-STEP 1/2/3 = ok（ginit / rev-parse HEAD / tree_names） | `G1 = fail(git cmd failed: show HEAD:fs2-nonexistent-file.txt)` | `STOP = fail-stop triggered by G1 (git cmd failed: show HEAD:fs2-nonexistent-file.txt)` | 后续标记 NO（未生成） | 4 件齐全 | **PASS** |
| **G2a** 证据缺失（不存在） | `require_evid` 指向**从未创建**的文件 | PRE-STEP 1 = ok（ginit）；`require_evid` 对**存在且非空**的前置文件通过（未熔断） | `G2a = fail(evidence missing or empty: …/g2a/evidence/G2a-injected-missing.txt)` | `STOP = fail-stop triggered by G2a (evidence missing or empty: …G2a-injected-missing.txt)` | 后续标记 NO | 4 件齐全；注入文件 CONFIRMED_ABSENT | **PASS** |
| **G2b** 证据缺失（空文件） | `require_evid` 指向 **0 字节**文件 | 同 G2a 前置（前置通过） | `G2b = fail(evidence missing or empty: …/g2b/evidence/G2b-injected-empty.txt)` | `STOP = fail-stop triggered by G2b (evidence missing or empty: …G2b-injected-empty.txt)` | 后续标记 NO | 4 件齐全；注入文件实测 0 字节 | **PASS** |
| **G3** 判定器错误 | `do_diff` 对**非 git 仓库**目录执行 → 内部 `git ls-tree` 失败 → 返回 90 | PRE-STEP 1/2/3 = ok（ginit / **基线 do_diff rc=0**，unclassified_count=0 / 注入目录在根内） | `G3 = fail(diff_unclassified=90)` | `STOP = fail-stop triggered by G3 (diff_unclassified=90)` | 后续标记 NO | 4 件齐全；`do_diff_rc=90` 独立留证 | **PASS** |

### 3.1 G3 的 90 返回码标注（定向修正 2）

- 原证据行 `G3 = fail(diff_unclassified=90)` /
  `STOP = fail-stop triggered by G3 (diff_unclassified=90)` **保持原文
  不变**（原始证据零改动）。
- 在**后续所有文档**中，该 **90** 一律明确标记为
  **`90 = classifier_error（判定器错误）`**——它是 `do_diff` 内部命令
  失败时的**错误返回码**，**不是**「未归类差异数量」（未归类数量在
  正常路径下为 N ≥ 0，V2.2 全回归实测为 0）。两者**不得混同**。
- 独立佐证（`g3/evidence/G3-postcheck.txt`）：
  `do_diff raw rc record: do_diff_rc=90 (want do_diff_rc=90)`；
  分类器错误证据：`fatal: not a git repository (or any of the parent
  directories): .git`；同时基线 `do_diff rc=0`、`unclassified_count=0`
  证明**注入点为该场景首个失败**（非提前失败冒充，§3.3 误判防护成立）。

### 3.2 通用验收清单核验（§3.3 六项）

| 检查项 | G1 | G2a | G2b | G3 |
|---|---|---|---|---|
| ① STOP 行存在且**触发来源归属正确**（逐字对应注入源） | ✅ | ✅ | ✅ | ✅（`diff_unclassified=90` = classifier_error） |
| ② 实际退出码 = 3 | ✅ | ✅ | ✅ | ✅ |
| ③ STOP 之后**后续步骤零执行**（后续标记未生成） | ✅ | ✅ | ✅ | ✅ |
| ④ 安全收尾完整（after-status + 前后 diff、inventory、summary 共 4 件） | ✅ | ✅ | ✅ | ✅ |
| ⑤ 写入全部位于本场景执行根内（`root_realpath` 各自独立；Gate 用 `assert_in_root` + TEMP 白名单 + ReparsePoint 探针） | ✅ | ✅ | ✅ | ✅ |
| ⑥ 无清理动作 | ✅（CLEANUP = skipped） | ✅ | ✅ | ✅ |

**误判防护核验**：四场景注入前准备步骤逐项留证全绿，注入异常均为
**首个失败**；未出现 INVALID 情形。

## 4. 证据引用（执行根 `%TEMP%/adll-fv0/run-20261018-fs2`）

| 证据 | 路径（相对执行根） | 用途 |
|---|---|---|
| 批次终检 | `99-fs2-batch-final.txt` | 四场景函数文件哈希一致、受保护档案哈希复核、逐场景 EXIT/STOP 汇总 |
| 载体脚本 | `run-p1-fs2.sh` | 哈希门禁 + 提取 + 注入逻辑全文 |
| 场景证据 | `g1/evidence/`、`g2a/evidence/`、`g2b/evidence/`、`g3/evidence/` 各含 `00-fs2-v22-hashgate.txt`、`99-summary.txt`、`G*-postcheck.txt`、`G*-inject-*` / `G*-do-diff-rc.txt`、`00-fs2-gitsanitize.txt`、`99-adll-status-before.txt` | 逐场景门禁、判定、STOP、退出码、收尾、注入证据 |
| 提取物 | `g*/fs2-functions.inc`（sha256 `d60e1623…`） | 证明熔断逻辑为 V2.2 **字节级**来源 |

**受保护档案复核（`99-fs2-batch-final.txt`，本次批次执行后实测）**：
run-fv0.sh = `0bb7a4cc…`（且 **FV-0 证据 75 份完好**）、
run-fv0-v2.sh = `7ef26ff6…`、run-fv0-v2.1.sh = `7506c899…`、
run-fv0-v2.2.sh = `f00f9cb5…`——**全部与既有基线一致，零改动**。

## 5. Gate-G-P1 解除登记（2026-10-18）

| 项 | 内容 |
|---|---|
| 门禁原状 | [p1-exception-branch-gate-plan.md](./p1-exception-branch-gate-plan.md) §1：FS2 三项/四场景未通过并登记前，**不得开始任何真实 AI 调用、不得安装 Agent SDK 或发起付费调用** |
| 裁定 | 用户**正式同意解除** Gate-G-P1 对 **FV-1 准备工作**的阻断 |
| **解除范围（严格限定）** | **仅**针对 FV-1 **准备工作**（文档编制、执行前审批清单准备） |
| **不构成** | **不构成 FV-1 执行批准**；不解锁 FV-1 执行、SDK 下载/安装、真实 AI 调用、付费调用、FV-2～FV-7 |
| 仍待满足的 FV-1 前置 | P3 人工授权（安装 + 首批付费调用总闸）、P4 金额上限填写、P5 专用测试 API Key 就位、P6 §5.0/§6 参数按锁定版本重核（[fv1-claude-agent-sdk-execution-plan.md](./fv1-claude-agent-sdk-execution-plan.md) §1） |
| 登记项 | ①四场景证据引用（§4）；②验证级别 = **function-level**（§2）；③遗留风险（§6） |
| 文本更新边界 | 本文为**新增登记**；[p1-exception-branch-gate-plan.md](./p1-exception-branch-gate-plan.md) §1 原文**未改动**（该文件的文本更新须单独授权），以本记录为门禁状态的最新权威登记 |

## 6. 遗留风险（未验证面，如实登记；不得据此宣称 P1 全路径覆盖）

1. **函数级 ≠ 整脚本**：未做整脚本注入；V2.2 中未提取的其余调用点
   （各格自身命令链、门禁、收尾编排）未逐一注入实测。
2. **合成场景 ≠ 真实故障**：真实 Git 损坏、权限拒绝、磁盘满、路径
   超长、编码/区域设置差异等未覆盖。
3. **G2 覆盖子面有限**：仅「文件不存在」与「0 字节」两种；未覆盖
   权限不可读、路径不可达、读取 IO 错误。
4. **G3 覆盖子面有限**：仅覆盖 `ls-tree` 因非仓库目录失败这一路径；
   `archive`/其他分类器内部失败子路径未覆盖。
5. **收尾自身失败未验证**：`fail_stop` 收尾（after-status/diff/
   inventory/summary）执行中若自身失败的行为未验证。
6. **环境面**：Windows 11 + git 2.50.1.windows.1 合成 fixture 范围；
   长时程、并发、真实大仓、网络远端均未验证。
7. **未覆盖**：FV-1～FV-7、依赖安装、AI 调用、ADR-C3/C4 终选、
   /speckit-tasks、/speckit-implement、任何清理授权。

## 7. 约束重申

1. 原始 FV-0 档案、V2 首次 FS1 失败记录、D1/D2/D3 偏差登记、V2.1/
   V2.2 证据、FS2 全部证据**永久保留**，不得删除、覆盖或改写。
2. 既有脚本（run-fv0.sh / run-fv0-v2.sh / run-fv0-v2.1.sh /
   run-fv0-v2.2.sh）**未被修改**（§4 哈希复核）。
3. fixtures 与证据**未清理**（CLEANUP = skipped）。
4. 本次解除**不得**解释为 FV-1 自动获批；FV-1 执行须用户独立批准。
5. 未验证分支不得宣称通过；本记录结论适用范围**仅限** §2 的函数级
   验证面。
6. 本记录为新增项目文档；既有档案零改动。