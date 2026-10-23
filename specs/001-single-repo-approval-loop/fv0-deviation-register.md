# FV-0 程序偏差登记（fv0-deviation-register.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**登记依据**: 用户人工裁定（2026-10-18）；验收状态
`TECHNICAL_ACCEPTED_WITH_PROTOCOL_DEVIATION`（见
[fv0-acceptance-record.md](./fv0-acceptance-record.md)）
**登记原则**: 如实登记、不隐瞒、不事后消除；原始失败记录一律保留。
**性质**: 偏差登记（引用既有证据，不修改、不覆盖任何原始证据）。

证据位置：FV-0 执行档案 `%TEMP%/adll-fv0/run-20261018-fv0/evidence/`
（路径经 `ADLL_FV0_ROOT` 注入，不硬编码；下文以 `<EVIDENCE>/` 指代）。

## D1 —— 失败即停规则违反【确认违反】

| 项 | 内容 |
|---|---|
| 规则 | fv0-execution-plan.md §8-2：「任一格『失败判定』命中 → 保留证据、停止后续格、出 99-summary，**不自行修复重试**」 |
| 事实 | 执行脚本 run-fv0.sh 对单格失败**无停止逻辑**（唯一退出为 assert_in_root 越界 ABORT）；F3 自动 fail 后继续执行 F4～F9、DIFF、REAL-REPO（各证据 mtime 时间线可证） |
| 证据 | `<EVIDENCE>/99-summary.txt` 行序（fail 行与后续格行共存于单次运行）、各证据文件 mtime、`../run-fv0.sh` 源码（无逐格熔断） |
| 人工裁定 | **确认违反失败即停规则。接受本次实验的技术证据，但不认定执行流程合规。** |
| 处置 | 偏差**永久登记**；技术证据按验收记录分项裁定使用；流程合规性**不予认定**。修复方案（含失败即停自检 FS1 设计）见 [fv0-script-fix-plan.md](./fv0-script-fix-plan.md)，执行另需授权 |
| 禁止 | 不得删除、覆盖或改写原始失败判定行；不得以任何事后手段「消除」本偏差 |

## D2 —— 判定更正轮的只读补充核查【登记保留】

| 项 | 内容 |
|---|---|
| 事实 | 执行收尾后进行一轮只读复核（`git check-attr` / `tar -tvf` 重列 / `readlink` / `cat-file` / `grep` 计数），用于 F3/F4/DIFF 人工复核与 F5 补记；未重跑测试矩阵、未修改 run-fv0.sh、未变更任何 fixture |
| 产物 | `<EVIDENCE>/99-postcheck.txt`（独立新增复核证据记录） |
| 人工裁定 | **保留只读补充核查及独立新增的复核证据记录。** |

## D3 —— F5 符号链接判定器漏采【登记保留】

| 项 | 内容 |
|---|---|
| 事实 | F5diff 目标字符串对照循环以 `[ -e ]` 判存在，该测试**跟随**悬空链接（escape.link → `../../escape.txt` 不存在）返回假，致 escape.link 目标字符串漏入自动对照记录 |
| 补救 | `<EVIDENCE>/99-postcheck.txt` 第 3 条补记：readlink/cat-file 均为 `../../escape.txt`；逃逸目标**内容**维持「未验证」 |
| 人工裁定 | **保留符号链接判定器漏采问题**（修复方案 P5 覆盖，执行另需授权） |

## 完整性声明

1. `99-summary.txt` 中 F3/F4/DIFF 原始 fail 行**逐字保留**，未删除、
   未覆盖、未改写。
2. 更正仅以 `99-verdict-corrections.txt` 追加记录形式存在，两层判定
  （原自动判定 / 人工复核结论）并存可追溯。
3. 本登记为新增项目文档，不修改任何既有证据。
