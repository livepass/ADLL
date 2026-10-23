# V2.1 全矩阵 F1～F9 离线回归 —— 最小授权范围提案（fv0-v21-regression-scope.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-18
**性质**: **授权范围提案（未批准、未执行）**。本文档仅定义最小执行
范围与验收标准；执行须用户单独授权，授权前不得启动任何回归步骤。
**依据**: [fv0-fs1-acceptance-record.md](./fv0-fs1-acceptance-record.md)
（FS1 PASS 及实测边界裁定）、[fv0-script-fix-plan.md](./fv0-script-fix-plan.md)
（P1～P5）、[fv0-deviation-register.md](./fv0-deviation-register.md)。

## 0. 目的

对 `run-fv0-v2.1.sh` 执行**一次**完整 F1～F9 离线合成矩阵回归，
实测此前未验证的修复项（P2/P3/P5、P4 规则 b/c）并取得 v2.1 全矩阵
基线证据。本回归**不验证** P1 异常分支（另行设计，不在本次范围），
**不覆盖**任何既有档案（FV-0 原始、V2 首次 FS1、V2.1 FS1 受控重试）。

## 1. 执行对象与范围（最小）

| 项 | 内容 |
|---|---|
| 脚本 | `run-fv0-v2.1.sh`（不修改；见 §4 决策项 D-R1 关于备选 v2.2） |
| 范围开关 | `FV0_SCOPE=full`（显式注入；FS1 格在此范围下整体跳过，不执行） |
| 执行根 | **全新** `%TEMP%` 子目录（如 `run-20261018-fv0v21-full`），经原路径安全门禁验证后使用 |
| 次数 | **仅一次**；失败即停、不自行修复、不自行重试 |
| 格序 | F1→F2→F3→F4→F5→F6→F7→F8→F9→正常收尾（DIFF 已按 P4 融入每格即时判定，无独立 DIFF 格） |
| 环境注入 | `ADLL_FV0_ROOT`（新执行根）、`ADLL_REPO_ROOT`（真实 ADLL 仓库，只读）、`FV0_SCOPE=full`；零网络、零依赖安装、零外部/付费 AI |

### 1.1 逐格验证目标映射

| 格 | fixture | 本轮实测目标（修复项） | 预期判定 |
|---|---|---|---|
| F1 | f1-sha1 | 基线 + P4 规则 a（已在 FS1 实测，本轮复验） | pass |
| F2 | f2-sha256 | SHA-256 归档一致性 | pass（若环境不支持 sha256 则 skipped，如实记录） |
| F3 | f3-lfs | **P2** 多行指针三行精确比较 | pass（指针逐字保留） |
| F4 | f4-submodule | **P3** 占位 vs 内容泄漏；**P4 规则 b** gitlink 占位归类 | pass（`mods/child/` 记为占位发现，内容级零泄漏） |
| F5 | f5-symlink | **P5** 悬空链接枚举（ls-tree mode 120000） | pass（两条链接目标字符串入册；逃逸目标**内容保持「未验证」**） |
| F6 | f6-ignore | export-ignore；**P4 规则 c** 父目录递归归类（`secret/key.txt`） | pass |
| F7 | f7-subst | export-subst 展开 + 内容差异归类 | pass |
| F8 | f8-canary | 打包一致性；零执行；canary 文本不入证据正文 | pass |
| F9 | 复用 f1-sha1 | archive 对 `.git` 零写入 vs worktree 写 `$GIT_DIR/worktrees/` | pass |
| 收尾 | — | REAL-REPO 前后对照、inventory、CLEANUP | pass / skipped |

各格 `do_diff` 结果均须 `diff_all_classified`（unclassified = fail，不放宽）。

## 2. 验收标准

1. 正常路径：全部格 pass（F2 允许 skipped），收尾 `EXIT_CODE = 0`、
   `FV0V2_DONE`；每格差异全部归类（unclassified_count=0）。
2. 失败即停路径（若任一格 fail）：`STOP` 行 + `EXIT_CODE = 3` +
   **后续格零产物** + after-status/inventory/summary 仍保存——此为 P1
   预期行为，**该轮即判「停止行为符合预期」，但矩阵结论为未完成**，
   按 §6 处置（不自行修复重试）。
3. 真实仓库前后 `status --porcelain=v1` 逐字节一致（diff 0 字节）。
4. 全部写入位于新执行根内（`assert_in_root` 常规保证）；无清理动作。
5. 新证据独立留证（§5），既有档案零改动（运行前后哈希复核）。

## 3. 安全边界（沿用已批准要求，不变）

1. **路径安全门禁**：`ADLL_FV0_ROOT`/`ADLL_REPO_ROOT` 环境注入（不
   硬编码）；TEMP/TMP 白名单严格前缀校验；PowerShell ReparsePoint
   探针（根及父目录）；`assert_in_root`（realpath 复核）。
2. **Git 环境净化**：unset 全部 `GIT_*` 干扰变量；空 gitconfig/
   template/hooks；`GIT_LFS_SKIP_SMUDGE=1`；逐调用 `-c` 身份。
3. **失败即停**：任一格失败/异常 → 保留证据、停止后续格、出汇总、
   exit 3；不自行修复、不自行重试。
4. **独立证据保留**：新执行根全新留证；**不覆盖** FV-0 原始档案、
   V2 首次 FS1、V2.1 FS1 受控重试的任何证据。
5. **只读边界**：真实 ADLL 仓库及其他仓库零写入、零 Commit/Push；
   合成仓库 `git init/commit` 仅限新执行根内（属授权范围）。
6. **零外部依赖**：零网络、零安装、零外部/付费 AI；敏感信息不入日志。
7. **不清理**：fixtures/evidence 全量保留；清理须单独授权。

## 4. 运行前决策项（授权时请一并裁定）

| # | 发现 | 选项 | 建议 |
|---|---|---|---|
| D-R1 | v2.1 两处**日志文案**在全矩阵语境失准（判定逻辑无影响）：①SCOPE 行硬编码「仅 F1 + FS1；F2～F9 本次不执行」；②`fail_stop` 的 STOP_RULE 行硬编码「F2-F9 未执行」（若在 F5 熔断，事实应为「后续格未执行」） | **A**：新建 `run-fv0-v2.2.sh`，仅改上述 2 行日志文案（零判定逻辑变化；v2.1 原样保留为 FS1 通过件）；**B**：按原样跑 v2.1，本提案预先声明该文案失准、以 `00-pathcheck.txt` 中 `scope=full` 实测值为准 | **A**（证据文案与事实一致优先；改动最小且可 diff 核对） |

## 5. 预期新证据清单（新执行根 `evidence/`）

`00-pathcheck.txt`、`00-gitsanitize.txt`、`99-adll-status-before/after/diff.txt`、
F1～F9 各格输出与 `F*diff-*`（含 classified）、`git-errors.log`、
`99-inventory.txt`、`99-summary.txt`（原始判定行逐字保留）；
另附独立复核记录（执行顺序、文件清单、受保护档案哈希复核、
真实仓库前后对照），格式参照 FS1 受控重试的 `99-v21-*` 系列。

## 6. 失败处置

任一格失败或异常 → 熔断停止（exit 3）→ **立即停止本次授权范围**，
如实提交结果（含原始失败行）等待人工裁定；不修复、不重试、不改判。
原始失败记录永久保留（与 D1 处置原则一致）。

## 7. 明确不包含 / 禁止

1. 不执行 FS1 自检（`FV0_SCOPE=full` 下该格不启用）。
2. 不进入 FV-1～FV-7；不执行 `/speckit-tasks`、`/speckit-implement`。
3. 不修改原始 FV-0、run-fv0-v2.sh、run-fv0-v2.1.sh 及其任何证据
  （D-R1 选项 A 仅新建 v2.2，不触碰既有文件）。
4. 不安装依赖、不调用外部/付费 AI、不访问网络。
5. 不修改真实业务仓库、ADLL-Knowledge；不 Git Commit/Push。
6. 不清理 fixtures/evidence；不修改 spec.md、宪章、AGENTS.md 及
   既有审批/验收/偏差登记。

## 8. 授权请求（供人工裁定引用）

> 请审核本最小授权范围。若批准，我将：（勾选 D-R1 选项）
> ① 创建新 TEMP 执行根并通过路径安全门禁；
> ② 以 `FV0_SCOPE=full` 对 run-fv0-v2.1.sh（或 v2.2）**执行一次**
>  完整 F1～F9 离线矩阵；
> ③ 按 §2 验收、§5 留证、§6 处置失败；
> ④ 提交结果后立即停止，等待人工审核。

**未获上述授权前，本提案不产生任何执行动作。**
