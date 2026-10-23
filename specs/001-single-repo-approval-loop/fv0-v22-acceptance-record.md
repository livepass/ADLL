# V2.2 全矩阵 F1～F9 回归人工验收记录（fv0-v22-acceptance-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**对象**: V2.2 全矩阵 F1～F9 离线回归（执行日 2026-10-18，
执行根 `%TEMP%/adll-fv0/run-20261018-fv0v22-full`）
**验收人**: 用户（人工裁定，2026-10-18）
**验收结论**: **回归通过（合成样本范围内）**——九项测试全部自动通过、
适用的 DIFF 分类结果无未归类差异、正常退出码为 0；P2～P5 在本轮
**合成样本范围内**验证通过。
**性质**: 人工验收记录（引用既有证据，不修改、不覆盖任何原始证据；
结论适用范围见 §4，不得外推）。

## 1. 人工裁定登记（2026-10-18，逐条）

1. 认可 V2.2 九项测试（F1～F9）全部自动通过、适用的 DIFF 分类结果
   无未归类差异、正常退出码为 0。
2. P2～P5 在本轮**合成样本范围内**验证通过。
3. 原始 FV-0 的 D1/D2/D3 偏差，以及 V2 首次 FS1 失败记录**继续永久
   保留**。
4. P1 的 Git 命令异常、证据缺失、判定器错误三条熔断分支**仍标记为
   未验证**，不得宣称全部覆盖。
5. ADR-C3 可采用**子进程 Git CLI + git archive** 作为推荐方案，但
   正式终选仍需**独立 ADR 决策和人工批准**（草案见
   [adr-c3-git-access-decision-draft.md](./adr-c3-git-access-decision-draft.md)）。

## 2. 分项验收裁定

| 项 | 自动判定（99-summary.txt 原文） | 人工裁定 |
|---|---|---|
| F1 | pass(archive_baseline_ok; diff_all_classified; content_a.txt_match) | 接受 |
| F2 | pass(; diff_all_classified) | 接受 |
| F3 | pass(pointer preserved verbatim (multi-line exact compare), no smudge) | 接受（P2 验证通过） |
| F4 | pass(gitlink in ls-tree, .gitmodules archived, submodule content absent; dir placeholder recorded as finding; file:// stayed inside fixtures; diff_all_classified) | 接受（P3、P4 规则 b 验证通过） |
| F5 | pass(links enumerated from git objects (dangling included); metadata-only; escape target content UNVERIFIED) | 接受（P5 验证通过）；**逃逸链接目标内容保持「未验证」**，不得升格 |
| F6 | pass(secret/key.txt excluded from archive, present in tree; diff_all_classified) | 接受（P4 规则 c 验证通过） |
| F7 | pass(placeholders expanded in archive (H=commit hash, AN=author); diff_all_classified) | 接受 |
| F8 | pass(canary files packaged consistently (archive vs tree); zero execution; content hashes recorded; diff_all_classified) | 接受 |
| F9 | pass(archive wrote nothing into .git; worktree writes .git/worktrees=yes (design R3.1 confirmed)) | 接受 |
| DIFF | 适用格（F1/F2/F4/F6/F7/F8）`unclassified_count=0`；F3/F5/F9 为专属比较（文件级 diff / 元数据对照 / .git 清单 diff）均一致 | **无未归类差异** |
| REAL-REPO | pass(ADLL 仓库 status 前后逐字节一致) | 接受 |
| EXIT | EXIT_CODE = 0（shell 实测一致）；无 STOP 行 | 接受 |

## 3. 证据引用（执行根 `%TEMP%/adll-fv0/run-20261018-fv0v22-full`）

| 证据 | 文件（相对 `evidence/`） | 用途 |
|---|---|---|
| 原始自动判定 | `99-summary.txt` | 九格 pass 行逐字保留 |
| 脚本差异与哈希 | `00-v22-diff-and-hashes.txt` | V2.1→V2.2 仅 2 处日志文案差异 + 四脚本哈希 |
| DIFF 归类汇总 | `99-v22-diff-classification.txt` | 逐格 classified 全文与 unclassified 计数 |
| 独立复核 | `99-v22-postcheck.txt` | 真实仓 diff 0 字节、受保护档案哈希复核、P2/P5 取证 |
| 执行顺序/清单 | `99-v22-order.txt`、`99-v22-inventory-full.txt` | mtime 全序、全量文件清单 |
| 各格证据 | `F1-sha1.txt`～`F9-*.txt`、`F*diff-*`、`F3-*-pointer.txt`、`F5-*.txt` | 逐格命令输出与对照记录 |
| 门禁留证 | `00-pathcheck.txt`、`00-gitsanitize.txt`、`00-preflight.txt` | TEMP 白名单、ReparsePoint、Git 净化 |

脚本哈希（本验收基线）：run-fv0-v2.2.sh =
`f00f9cb5c61c9f455e6d743ca2ace1cc6cb76a63296362981c357b18e7336ca1`。

## 4. 结论适用范围（不得外推）

1. 本轮验证对象为**合成 fixture 离线矩阵**（git 2.50.1.windows.1 /
   Windows 11），**不代表**真实大仓、网络远端、特殊文件系统或长时程
   运行场景。
2. P1 三条异常分支（Git 命令异常 / 证据缺失 / 判定器错误）**未实测**，
   不得宣称 P1 全路径覆盖；其离线验证方案见
   [p1-exception-branch-gate-plan.md](./p1-exception-branch-gate-plan.md)。
3. F2 为条件通过项（依赖环境 sha256 支持；换环境可能 skipped）。
4. F5 逃逸链接目标**内容**维持「未验证」。
5. 本验收**不包含**：FV-1～FV-7、依赖安装、付费 AI 调用、ADR-C3/
   ADR-C4 终选、/speckit-tasks、/speckit-implement、清理授权。

## 5. 约束重申

1. 原始 FV-0 档案、V2 首次 FS1 失败记录、D1/D2/D3 偏差登记、V2.1
   FS1 证据**永久保留**，不得删除、覆盖或改写（本登记写入前已复核：
   原始证据 75 份完好、V2/V2.1/原始 run-fv0.sh 哈希一致）。
2. P1 未验证分支不得宣称通过；后续验证结果另行登记。
3. 本记录为新增项目文档；既有档案零改动。
