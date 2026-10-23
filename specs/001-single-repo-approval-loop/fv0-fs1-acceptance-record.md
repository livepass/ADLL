# FS1 失败即停自检人工验收记录（fv0-fs1-acceptance-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**对象**: FS1 失败即停自检（P1/D1 修复回归验证；两次执行）
**验收人**: 用户（人工裁定，2026-10-18）
**验收结论**: **FS1 专项验收 PASS**——F1 正常通过，FS1 故意失败，
触发 STOP，实际退出码为 3，F2～F9 未执行（失败后立即停止即预期行为）。
**性质**: 人工审核结论独立登记（引用既有证据，不修改、不覆盖任何
原始证据；与既有验收/偏差登记并存）。

## 1. 人工裁定登记（2026-10-18，逐条）

1. **FS1 专项验收 PASS**：F1 正常通过，FS1 故意失败，触发 STOP，
   实际退出码为 3，F2～F9 未执行。
2. **永久保留**：V2 首次 FS1 失败记录及原始 FV-0 的 D1/D2/D3 偏差
   继续永久保留，**不得覆盖**。
3. **实测边界（P1）**：V2.1 的 P1 失败即停**主路径**已取得实测证据；
   **尚未验证的异常分支不得宣称通过**。
4. **未实测项**：P2/P3/P5 及 P4 部分规则仍未实测。

## 2. 执行历史与证据引用

证据位置均以 `ADLL_FV0_ROOT` 环境注入（下文以 `<ROOT>` 指代执行根，
按 AGENTS.md §3 不硬编码本机绝对路径）。

### 2.1 第一次 FS1（不通过；证据永久保留）

| 项 | 内容 |
|---|---|
| 执行根 | `%TEMP%/adll-fv0/run-20261018-fv0v2-fs1` |
| 脚本 | `run-fv0-v2.sh`（sha256 基线 `7ef26ff6…7c33`，此后未改动） |
| 结果 | **不通过**：`F1 = fail(… content_a.txt_mismatch)` → 在 F1 即熔断，FS1 未执行 |
| 根因（只读诊断） | `content_diff` 生成文件名追加多余 `.txt`（`*.txt.txt`），断言读取 `*.txt` 失配，`diff -q` 错误被误分类为 mismatch |
| 附带实测 | P1 熔断在**真实误判失败路径**生效：STOP 行、exit 3、F2～F9 零产物、after-status/inventory/summary 保存（不改变该轮不通过判定） |
| 处置 | 全部证据**永久保留**，不覆盖、不删除；不自行重试（遵从当场指令） |

### 2.2 v2.1 最小修复（仅 2 处实质修改）

新脚本 `run-fv0-v2.1.sh`（独立修订版本；V2 原件零改动，哈希复核一致）：
① `content_diff` 文件命名统一为 `$P-content-{tree,archive,diff}-$path`
（`$path` 自带扩展名，不再追加 `.txt`）；② F1 内容对照**三分错误分类**
（`content_compare_file_missing` / `content_a.txt_mismatch(diff_rc=1)` /
`content_compare_cmd_error`）。未跳过比较、未放宽断言。

### 2.3 第二次受控重试（PASS；本记录验收对象）

| 项 | 内容 |
|---|---|
| 执行根 | `%TEMP%/adll-fv0/run-20261018-fv0v21-fs1` |
| 范围 | `FV0_SCOPE=f1-fs1`，单次执行（2026-10-18 08:46:20Z～08:46:22Z） |
| 汇总原文 | `F1 = pass(archive_baseline_ok; diff_all_classified; content_a.txt_match)`；`FS1 = fail(selftest: deliberate mismatch（预期 FAIL — 触发失败即停）)`；`STOP = fail-stop triggered by FS1`；`EXIT_CODE = 3` |
| 退出码 | 脚本内 `EXIT_CODE = 3` 与 shell 实测 `ACTUAL_EXIT_CODE=3` 一致 |
| 修复点实测 | `F1diff-content-tree-a.txt` = `F1diff-content-archive-a.txt`（各 6B），`F1diff-content-diff-a.txt`（0B）→ `content_a.txt_match` |
| F2～F9 缺席 | 各格证据计数全部 = 0（`99-v21-postcheck.txt`） |
| 收尾顺序 | F1 证据 → `FS1-failstop.txt` → after-status → diff → inventory → summary（P1 熔断收尾①②③④成立，`99-v21-order.txt`） |
| 真实仓库 | 前后 status 逐字节一致（diff 0 字节） |
| 独立留证 | `99-v21-summary-verbatim.txt`（汇总逐字副本）、`99-v21-order.txt`、`99-v21-inventory-full.txt`、`99-v21-postcheck.txt`（F2～F9 缺席、受保护对象哈希复核） |

## 3. 实测覆盖与未验证边界（裁定 3、4 的落实）

### 3.1 P1 失败即停 —— 已实测（主路径）

| 触发路径 | 实测情况 |
|---|---|
| 真实判定失败（误判 fail） | 已实测（第一次 FS1，F1 即熔断） |
| 故意判定失败（FS1 预期 FAIL） | 已实测（第二次，STOP + exit 3 + F2～F9 零产物） |

### 3.2 P1 异常分支 —— **未验证，不得宣称通过**

| 分支 | 状态 |
|---|---|
| Git 命令异常触发熔断 | 未实测 |
| 证据缺失（`require_evid`）触发熔断 | 未实测 |
| 判定器错误（`do_diff` 返回 90）触发熔断 | 未实测 |

### 3.3 其余修复项 —— 未实测（P4 部分例外）

| 修复项 | 状态 |
|---|---|
| P2（F3 多行 LFS 指针比较） | 未实测 |
| P3（F4 空目录占位 vs 内容泄漏） | 未实测 |
| P5（F5 悬空符号链接枚举） | 未实测 |
| P4 规则 a（tar 目录头条目） | **部分实测**（F1 的 DIFF 中 `docs/ = tar 目录头条目（预期）`，`unclassified_count=0`） |
| P4 规则 b（gitlink 空目录占位） | 未实测 |
| P4 规则 c（export-ignore 父目录递归） | 未实测 |
| P4 全矩阵「每格即时判定」 | 部分实测（F1 格内即时判定生效） |

## 4. 约束重申（验收裁定的组成部分）

1. 第一次 FS1 失败记录（`run-20261018-fv0v2-fs1` 全量证据）、原始
   FV-0 档案及 D1/D2/D3 偏差登记**永久保留**，不得删除、覆盖或改写。
2. P1 未验证异常分支、P2/P3/P5 及 P4 未实测规则**不得宣称通过**；
   任何后续验证结果另行登记。
3. 本记录为新增项目文档；既有档案（FV-0 原始、V2、V2.1 两次 FS1
   证据）零改动（本登记写入前已复核：原始 FV-0 证据 75 份完好，
   V2 哈希与基线一致）。

## 5. 验收不包含

本验收不包含：V2.1 全矩阵 F1～F9 离线回归（授权范围另行提交、
待单独授权）、FV-1～FV-7、依赖安装、付费 AI 调用、
`/speckit-tasks`/`/speckit-implement`、清理授权、ADR-C3 终选批准。
