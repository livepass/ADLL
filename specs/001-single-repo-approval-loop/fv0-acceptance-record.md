# FV-0 人工验收记录（fv0-acceptance-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**对象**: FV-0 纯离线可行性验证（执行日 2026-10-18）
**验收人**: 用户（人工裁定，2026-10-18）
**验收结论**: **`TECHNICAL_ACCEPTED_WITH_PROTOCOL_DEVIATION`**
—— 技术结果接受；**执行流程不合规**（偏差见
[fv0-deviation-register.md](./fv0-deviation-register.md)），
不得据此认定执行流程合规。
**性质**: 人工验收记录（引用既有证据，不修改、不覆盖任何原始证据）。

## 1. 分项验收裁定

| 格 | 自动判定（99-summary.txt 原文，逐字保留） | 人工裁定 |
|---|---|---|
| F1/F2/F5/F6/F7/F8/F9 | pass | **自动判定通过**，接受 |
| F3 | fail(archive content is not pointer text) | 自动失败；人工复核后**技术结果通过**（expected/`git show`/`tar -xOf` 三段逐行一致） |
| F4 | fail(archive/tree mismatch…) | 自动失败；人工复核后**技术结果通过**（子模块内容不含；gitlink 空目录占位发现保留） |
| DIFF | fail(存在未归类差异) | 自动失败；人工复核后**差异全部归类**（3 处分类器缺口见修复方案 P4） |
| F5 逃逸符号链接目标内容 | 「未验证」 | **保持「未验证」**，不得升格表述 |
| REAL-REPO | pass | 接受（前后 status 逐字节一致；不作绝对无写入保证） |
| CLEANUP | skipped | 接受（fixtures/evidence 全量保留） |

## 2. 证据引用（FV-0 执行档案）

执行根：`%TEMP%/adll-fv0/run-20261018-fv0`（路径经 `ADLL_FV0_ROOT`
环境注入，实际规范化值与校验结果见该档案 `evidence/00-pathcheck.txt`；
按 AGENTS.md §3 不在项目文档硬编码本机绝对路径）。以下文件名均相对
该执行根 `evidence/`：

| 证据 | 文件 | 用途 |
|---|---|---|
| 原始自动判定 | `99-summary.txt` | 含 F3/F4/DIFF 原始 fail 行，**不得删除或覆盖** |
| 判定更正 | `99-verdict-corrections.txt` | 两层判定记录：原行保留 + 更正理由 + 修正后结论（区分自动/人工） |
| 只读复核取证 | `99-postcheck.txt` | check-attr 语义、f4 目录占位、逃逸链接对照、F3 三段比对（D2） |
| 时间线/脚本 | `../run-fv0.sh` | mtime 2026-10-18 11:02:46 +0800；执行后未改动 |
| 各格证据 | `F1-sha1.txt`～`F9-*.txt`、`F*diff-*` | 逐格命令输出与差异清单 |
| 真实仓库存证 | `99-adll-status-before/after/diff.txt` | diff 0 字节 |
| 清单 | `99-inventory.txt` | 执行根全量文件清单 |
| ADR 影响 | `99-adr-c3-impact.md` | 7 项发现 + 5 条结论（已回填 research.md ADR-C3） |

## 3. 约束重申（验收裁定的组成部分）

1. **不得删除或覆盖任何原始失败记录**（含 99-summary.txt 中
   F3/F4/DIFF 行）；更正只允许以追加的更正记录形式存在。
2. F5 逃逸链接目标内容保持「未验证（不跟随、不解包）」，不得升格。
3. 本记录与偏差登记为新增项目文档；FV-0 执行档案中的原始证据
   零改动。
4. 测试脚本缺陷按
   [fv0-script-fix-plan.md](./fv0-script-fix-plan.md)（另行人工审核）
   处置；**原 run-fv0.sh 保留为证据不修改**，修复落于后继脚本版本。

## 4. 验收不包含

本验收不包含：FV-1～FV-7 执行、依赖安装、付费 AI 调用、
`/speckit-tasks`/`/speckit-implement`、ADR-C3 终选批准、清理授权。
