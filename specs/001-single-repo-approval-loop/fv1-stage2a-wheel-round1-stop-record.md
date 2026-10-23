# FV-1 阶段 2A-Wheel 第 1 轮（获取）—— 停止记录（fv1-stage2a-wheel-round1-stop-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **停止记录**。依用户 2026-10-19 方案 (a) 授权执行「受控依赖解析与真实
Wheel 获取」；本轮在**下载开始前**的候选-索引哈希比对中命中「哈希不符」，按
停止规则**记录精确差异并停止，未下载任何 Wheel**。
**执行根**：`%TEMP%/adll-fv0/run-20261019-fv1-wheel`（全新，路径安全检查通过；
`wheelhouse/` 为**空**，含 `meta/` 31 个权威元数据 JSON、`tools/` 两个脚本、
`evidence/` 记录）。

## 1. 本轮实际执行（零下载）

| 步骤 | 结果 |
|---|---|
| 前置 | 执行根路径白名单/ReparsePoint 探针通过（`01-2awheel-preflight.txt`） |
| 元数据重取 | 以 `curl` 直读 PyPI 只读元数据端点 `https://pypi.org/pypi/<pkg>/<ver>/json`（**31 个**），全部 `HTTP 200`，未跟随重定向（`01-2awheel-meta-fetch.txt`） |
| 候选-索引哈希比对 | 脚本 `tools/compare_all.py` 逐包比对（文件名/matcher/版本/host/`is_whl`/sha256）→ **30 MATCH / 1 MISMATCH**（`01-2awheel-candidate-diff.txt`） |
| 下载 | **未执行**（`wheelhouse/` = 0 文件，0 字节） |

## 2. 命中停止条件的精确差异

| 项 | 值 |
|---|---|
| 包 | `cryptography` v50.0.2 |
| 目标 wheel | `cryptography-50.0.2-cp311-abi3-win_amd64.whl`（大小为 **3,824,692** 字节） |
| **候选（阶段 2A 记录，错误）** | `fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb` |
| **权威（curl 直读 PyPI JSON，正确）** | **`7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c`** |
| 目的域名 | `files.pythonhosted.org`（符合授权） |

其余 **30 个包全部 MATCH**（含 SDK wheel `ed1814b0…`、pydantic-core `132529c8…`、
cffi `f53e442b…`、pywin32 `b457f6d6…`、rpds-py `5ce8943f…` 等）。

## 3. 根因（如实登记，不掩盖）

- 阶段 2A 的候选哈希来自 **WebFetch 的摘要输出**（其内部用小型模型转述网页），
  对 `cryptography` 的两处哈希发生了**转述/编配错误**：
  - `cp311-abi3-win_amd64`：WebFetch 报 `fa8f5efb…`，权威实为 `7afa5a66…`；
  - `cp314-cp314t-win_amd64`：WebFetch 报 `f785f616…`，权威实为 `78198641…`
    （该 wheel 非本平台目标，故不进入锁清单，但佐证其为转述错误）。
- **结论**：错误来自**工具链（WebFetch 摘要）**，而非索引侧变更——`cryptography
  50.0.2` 早于本阶段上传，PyPI JSON 稳定。仍按规则将「cryptography 是否在此间被
  换包」列为**不可混淆为"已排除"**：本次以 curl 直读权威值离线冻结，后续下载比对
  即最终裁决。
- **教训（写入后续纪律）**：**哈希、URL、大小、许可证等精确值必须用 `curl` 直读
  权威 JSON 取得**（机器精读，本阶段即如此），**不得依赖 WebFetch 摘要转述**；
  这与 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §9-L7「以解析器/索引哈希
  为准」方向一致，并进一步收紧为「逐包 curl 直读 + 二次核对」。

## 4. 责令遵守的停止规则命中情况

| 规则 | 命中 |
|---|---|
| 计划外网络地址 | 否 |
| 清单外工件 | 否 |
| 需要 sdist / 源码构建 | 否 |
| **哈希不符** | **是（cryptography 1 处）** → 停止 |
| 依赖解析冲突 | 否（解析器未运行，本轮为候选比对） |
| 未批准的新依赖 | 否 |
| 证据缺失 / 前置失败 | 否 |

## 5. 未做与下一步（等待人工）

1. **未下载任何 Wheel**、未生成 `lock.txt`（本轮未到该步）、未创建 venv、未安装、
   未运行 SDK/CLI、未调用模型 API、未使用 API Key；未修改网络/防火墙设置、
   未修改真实仓库或 ADLL-Knowledge、未清理历史证据、无 Git Commit/Push。
2. **等待裁定的唯一点**：是否同意将 `cryptography==50.0.2` 的哈希更正为权威值
   **`7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c`**
   （文件名/大小不变：`cryptography-50.0.2-cp311-abi3-win_amd64.whl`，3,824,692 B），
   并**重新授权**第 2 轮下载（31 个 wheel，其余 30 个哈希已被二次核验正确）。
3. 在上述更正获单独批准前，**不得**自行继续下载、不得自行修复、不得重试。

## 6. 证据引用（执行根 `%TEMP%/adll-fv0/run-20261019-fv1-wheel`）

| 证据 | 路径 |
|---|---|
| 前置/路径安全检查 | `evidence/01-2awheel-preflight.txt` |
| 31 次元数据获取记录（URL+HTTP） | `evidence/01-2awheel-meta-fetch.txt` |
| **候选-索引比对（30 MATCH / 1 MISMATCH）** | `evidence/01-2awheel-candidate-diff.txt` |
| 停止汇总 | `evidence/99-2awheel-round1-stop.txt` |
| 权威元数据快照（31 个 JSON） | `meta/*.json` |
| 工具脚本 | `tools/prepare_manifest.py`、`tools/compare_all.py` |