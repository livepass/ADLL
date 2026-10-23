# FV-1 阶段 2A-Wheel 第 2 轮 —— 执行记录（fv1-stage2a-wheel-round2-execution-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **第 2 轮受控 Wheel 获取与离线解析执行记录**（依用户 2026-10-19 第二轮授权）。
**执行根（全新独立）**：`%TEMP%/adll-fv0/run-20261019-fv1-wheel2`
（**未复用**第一轮目录 `run-20261019-fv1-wheel`；路径安全检查通过）。
**结论**：31/31 Wheel 下载并**逐包字节大小 + SHA-256 双校验全部通过**；离线解析
**自洽通过**；SDK 内嵌 CLI 与 **Anthropic 签名 manifest 逐字节一致**；**未触发任何
停止条件**。

## 0. 授权与执行边界（严格遵守）

- 仅下载预先列明的 **31 个 Wheel**（不作增/替/升级）；索引查询仅 `pypi.org`，
  工件获取仅 `files.pythonhosted.org`；**零重定向**（curl `--max-redirs 0`，检响应头）。
- 禁 sdist/源码构建/安装器/CLI 独立下载；下载后逐包**立即**核对字节大小与 SHA-256。
- **未**创建 venv、未安装、未执行 SDK/CLI、未用 API Key、未调用模型、未修改网络配置、
  未修改真实仓库/ADLL-Knowledge、未清理历史证据、未 Git Commit/Push。

## 1. 第二轮实际下载清单与完整 SHA-256 校验结果（31/31 全部通过）

逐包核对依据：磁盘文件 `wheelhouse/*.whl` 的**实际字节大小**与 `sha256sum` 对照
`evidence/01-2awheel-r2-compare.txt`（来自 PyPI 索引的权威值）。**零 mismatch**。

| 包 | 版本 | 字节大小 | SHA-256（磁盘实测 = 索引权威值） |
|---|---|---|---|
| annotated-types | 0.8.0 | 13,427 | `f072f4d8…9419e0` |
| anyio | 4.15.1 | 132,079 | `6152fdbb…c7ed101` |
| attrs | 26.1.0 | 67,548 | `c647aa4a…43ac309` |
| cffi | 2.1.1 | 185,919 | `f53e442b…ec44339a` |
| **claude-agent-sdk** | **0.2.168** | **117,292,475** | `ed1814b0…23a5b35` |
| click | 8.5.0 | 125,251 | `255bc959…4ee360` |
| **cryptography** | 50.0.2 | 3,824,692 | **`7afa5a66…d89879c`**（更正值） |
| h11 | 0.16.0 | 37,515 | `63cf8bbe…31cb6c86` |
| httpcore2 | 2.13.1 | 83,423 | `e1e05d4f…3db73d0a` |
| httpx2 | 2.13.1 | 95,597 | `6dff50fa…96d2f9a4` |
| idna | 3.20 | 69,583 | `ab7ae712…14582c` |
| jsonschema | 4.26.0 | 90,630 | `d489f152…2dab50ce` |
| jsonschema-specifications | 2025.9.1 | 18,437 | `98802fee…210cc6fe` |
| mcp | 2.3.0 | 368,664 | `dd0c44c0…34b2377` |
| mcp-types | 2.3.0 | 69,108 | `968efdbd…af76d91d` |
| opentelemetry-api | 1.45.1 | 60,256 | `b31553ef…87fdedfb` |
| pycparser | 3.11 | 51,178 | `51d5a8ba…1729cd80` |
| pydantic | 2.14.1 | 488,106 | `9195d967…0d6b454` |
| pydantic-core | 2.50.1 | 2,172,522 | `132529c8…ead62498` |
| pyjwt | 2.15.1 | 33,860 | `42d59d63…eec5e193` |
| python-multipart | 0.0.32 | 30,042 | `ff6d3f77…821fe2e23` |
| pywin32 | 312 | 6,914,841 | `b457f6d6…19a93bc` |
| referencing | 0.37.0 | 26,766 | `381329a9…cc7692231` |
| rpds-py | 2026.9.1 | 222,923 | `5ce8943f…ae70c86f` |
| sniffio | 1.3.1 | 10,235 | `2f6da418…100525a2` |
| sse-starlette | 3.5.0 | 17,407 | `3e6e1070…dd8b7997` |
| starlette | 1.8.0 | 79,612 | `dfdd6b29…e3c4656f` |
| truststore | 0.10.5 | 19,017 | `9aaaedae…df78951c` |
| typing-extensions | 4.16.0 | 45,571 | `481caa48…6370c2e8` |
| typing-inspection | 0.4.4 | 14,750 | `65b8397b…32f3f147` |
| uvicorn | 0.54.0 | 87,427 | `505bdb0f…d4f67faf` |

（完整 64 位哈希见执行根 `evidence/99-wheels-final-sha256-list.txt`；下载过程每包
逐项 `size actual==expected` 与 `sha actual==expect` 记录于
`evidence/02-2awheel-download.log`，末尾 `ALL_VERIFIED = all wheels downloaded and hash-verified`。）

## 2. 第一轮与第二轮差异 / 纠错记录

| 项 | 内容 |
|---|---|
| 原候选（第 1 轮，错误） | `cryptography==50.0.2` → `fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb` |
| 更正后（第 2 轮，权威） | `cryptography==50.0.2` → **`7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c`** |
| 文件名 / 大小 | 不变：`cryptography-50.0.2-cp311-abi3-win_amd64.whl`，3,824,692 字节 |
| 来源 | PyPI 索引用 `curl` 直读权威 JSON（`https://pypi.org/pypi/cryptography/50.0.2/json`） |
| 原因 | 第 1 轮候选哈希取自 WebFetch **摘要转述**（不可靠）；`cp311-abi3` 与 `cp314` 两处被错配 |
| 保留 | 第 1 轮原始失败记录、原候选哈希、日志与证据**永久保留，未覆盖未改写**（`run-20261019-fv1-wheel` 原样保留） |

其余 **30 个候选哈希与索引一致**（无需更正）。

## 3. 离线解析报告（本地 Wheel 集合，零网络）

命令（`evidence/03-2awheel-offline-dryrun.txt`）：
```
python -m pip --isolated install --dry-run --ignore-installed --no-index \
  --find-links <wheelhouse> --only-binary=:all: --require-hashes \
  -r <lock.txt> --no-cache-dir --retries 0
```

- **结果：pip exit 0**；`Looking in links: <本地 wheelhouse>`，随后 `Processing …` 逐项读取
  **31 个本地 wheel**，最后 `Would install …` 列出**恰好 31 个包**（与第 1 节清单一一对应）。
- **零网络**：`--no-index` 下 pip 只读本地 `--find-links`，无任何 HTTP（`--isolated` 屏蔽
  用户 pip 配置，`--retries 0`）。
- **无新依赖、无版本冲突、无平台不兼容、闭包完整**；`--only-binary=:all:` + `--require-hashes`
  下**无 sdist、无源码构建、无 build 依赖回退**。

## 4. 完整依赖锁定清单（`lock.txt`，离线、无 URL）

`evidence/lock.txt` 共 31 行，每行 `包名==版本 --hash=sha256:<64hex>`；经核验**不含
任何 URL / 主机名**（`://` / `pypi.org` / `files.pythonhosted.org` / `downloads.claude.ai`
均为 0 命中）。

```
annotated-types==0.8.0 --hash=sha256:f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0
anyio==4.15.1 --hash=sha256:6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101
attrs==26.1.0 --hash=sha256:c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309
cffi==2.1.1 --hash=sha256:f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a
claude-agent-sdk==0.2.168 --hash=sha256:ed1814b0dd1c113bdaf3e51e6a67aa5b96b8f5c5839a43aeb6ae1e6ed23a5b35
click==8.5.0 --hash=sha256:255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360
cryptography==50.0.2 --hash=sha256:7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c
h11==0.16.0 --hash=sha256:63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86
httpcore2==2.13.1 --hash=sha256:e1e05d4f25f7d7d496bfb96748f6f4b67657b03da069b3a68c36069f3db73d0a
httpx2==2.13.1 --hash=sha256:6dff50fabc270ee5fd25d845d0b078ed20564579744d6d962850975996d2f9a4
idna==3.20 --hash=sha256:ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c
jsonschema==4.26.0 --hash=sha256:d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce
jsonschema-specifications==2025.9.1 --hash=sha256:98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe
mcp==2.3.0 --hash=sha256:dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377
mcp-types==2.3.0 --hash=sha256:968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d
opentelemetry-api==1.45.1 --hash=sha256:b31553efa588ae44bc306f863c785c5333a9ecc091248c6ee68b4b6c87fdedfb
pycparser==3.11 --hash=sha256:51d5a8ba2be0bbe440b99d2112604c95bbbc3c2748a64260186c541e1729cd80
pydantic==2.14.1 --hash=sha256:9195d967ec791692a04438115466764fb8b9a27b31f14a760437694f40d6b454
pydantic-core==2.50.1 --hash=sha256:132529c83901437ff642f585216831bf5fd7a91df66829907e155192ead62498
pyjwt==2.15.1 --hash=sha256:42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193
python-multipart==0.0.32 --hash=sha256:ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23
pywin32==312 --hash=sha256:b457f6d628a47e8a7346ce22acb7e1a46a4a78b52e1d17e1af56871bd19a93bc
referencing==0.37.0 --hash=sha256:381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231
rpds-py==2026.9.1 --hash=sha256:5ce8943f79c2210f7abcc28e86367b03b28d95027fd01c46d2472373ae70c86f
sniffio==1.3.1 --hash=sha256:2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2
sse-starlette==3.5.0 --hash=sha256:3e6e1070df3f0f5d9cea81496de92dbb72f6721871d99748ece67441dd8b7997
starlette==1.8.0 --hash=sha256:dfdd6b29c26483288088d990eee59631dedadd66ce20d203402a7ca8e3c4656f
truststore==0.10.5 --hash=sha256:9aaaedaefaf06d8b206278cf8b5012bc897f485a874503501e12d776df78951c
typing-extensions==4.16.0 --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8
typing-inspection==0.4.4 --hash=sha256:65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147
uvicorn==0.54.0 --hash=sha256:505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf
```

（该锁文件即 2B 离线安装的直接输入 `-r lock.txt`；**不含远程 URL**。）

## 5. SDK Wheel 内嵌 CLI 静态检查（未执行任何二进制）

| 项 | 结果 |
|---|---|
| 内嵌 CLI 路径 | `claude_agent_sdk/_bundled/claude.exe` |
| wheel 内 `file_size` | **271,840,416** 字节（`compressed_size` 117,136,578） |
| 提取后磁盘 `sha256` | **`84d61feeb1a07e5a5b3354d68432591cac18a5d38a419a30d86d0f3ad8cba397`** |
| 与 Anthropic 签名 manifest 比对 | **逐字节一致**（第 2 节 P-2 已取得并验签的 `manifest.json` `platforms.win32-x64.checksum` = `84d61fee…cba397`，`size` = 271,840,416） |
| Authenticode（`Get-AuthenticodeSignature`，离线读） | **`Status = Valid`**，签名者 **`CN="Anthropic, PBC"`**（与官方「Windows: signed by Anthropic, PBC」一致） |
| 内置 CLI 版本 | `_cli_version.py` → `__cli_version__ = "2.1.301"`（与 release 说明一致） |
| SDK 版本 | `_version.py` → `__version__ = "0.2.168"` |
| SDK 许可证 | `METADATA` `License: MIT` + `License :: OSI Approved :: MIT License`；`LICENSE` = MIT（Copyright 2025 Anthropic, PBC） |

**供应链结论（一字不夸大）**：SDK 0.2.168 的 `claude_agent_sdk/_bundled/claude.exe`
与 Anthropic 官方 **GPG 签名 manifest** 中 `win32-x64` 二进制**哈希逐字节一致**，
且该二进制携带 **有效的 Authenticode 签名（"Anthropic, PBC"）**。即：本次获得的
内嵌 CLI 可溯源至 Anthropic 官方发布物。**仍不构成生产级安全验证**（用户已裁定
「仅用于隔离合成测试的有限风险」）。

## 6. 网络访问与安全门禁证据

| 项 | 证据/结果 |
|---|---|
| 执行根路径（TEMP 白名单 + 非 reparse 点） | `01-2awheel-r2-preflight.txt`（通过） |
| 索引元数据（31 次 `pypi.org` GET，HTTP 200，零重定向） | `01-2awheel-r2-meta-fetch.txt` |
| 工件获取（31 次 `files.pythonhosted.org`，零重定向，`.headers` 均 `HTTP 200` 无 `Location`） | `02-2awheel-download.log` + `wheelhouse/*.headers` |
| **计划外网络地址** | **无**（仅 `pypi.org` 与 `files.pythonhosted.org` 两类授权域） |
| **清单外工件 / sdist / 源码构建 / 安装器 / CLI 独立下载** | **无** |
| 逐包字节大小 + SHA-256 核验 | `02-2awheel-download.log`（31/31 `VERIFIED = ok`） |

## 7. 阶段 2B 是否具备执行条件的明确结论

| 前置（依据 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §3B-1） | 状态 |
|---|---|
| B0-1 锁文件/交付物经**人工审核** | **待用户审核批准（即 2B 批准本身）** |
| B0-2 wheelhouse 完整（31 包、零 sdist、哈希与锁文件一致） | ✅ **满足**（§1 逐包核验） |
| B0-3 解释器 64 位/路径（Python 3.12.10；全 wheel 为 cp312/win_amd64 或 py3-none-any） | ✅ **满足**（D-PY 已裁；本轮 wheel 平台标签契合） |
| B0-4 无托管设置 | ⚠️ 阶段 1 已核无 `managed-settings.json`；**2B 执行时复核** |
| B0-4b 离线解析闭包自洽（`--no-index`） | ✅ **满足**（§3 pip exit 0） |
| B0-5 断网条件（pip 层 `--no-index --find-links` + OS 层由**人工**断网） | ⚠️ **2B 执行时由人工建立**（OS 层断网不改全局防火墙，方案 §4.2） |

**结论**：阶段 2B 的**软件侧前置已满足**（锁文件定稿、wheelhouse 完整且哈希一致、
离线解析自洽、平台兼容、内嵌 CLI 已溯源核验）。**尚缺**：(a) 用户对锁文件与交付物的
**人工审核/批准**（即 2B 执行批准）；(b) 2B 执行时的 **OS 层断网人工操作**。二者齐备后，
2B 可按 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §3B-2/3B-3/3B-4 离线安装。

## 8. 未执行 / 未修改（如实声明）

未创建 venv · 未安装/运行 SDK/CLI（含未运行 `claude.exe`、未 `doctor`）· 未调用模型
API、未使用 API Key · 未修改宿主网络/防火墙配置 · 未修改真实仓库或 ADLL-Knowledge ·
未清理历史证据（第 1 轮目录与全部证据原样保留）· 无 Git Commit/Push · 未触发停止。
项目内仅**新增**本记录文件；既有已批准文档未改动。

## 9. 证据引用（执行根 `%TEMP%/adll-fv0/run-20261019-fv1-wheel2`）

`evidence/01-2awheel-r2-preflight.txt`（路径安全）· `01-2awheel-r2-meta-fetch.txt`
（索引元数据 31 次）· `download-manifest.txt`（8 列工件清单，含 URL）· `lock.txt`
（离线 31 行）· `01-2awheel-r2-compare.txt`（候选-索引比对 31 MATCH）·
`02-2awheel-download.log`（每包 size+sha 核验）· `03-2awheel-offline-dryrun.txt`
（离线解析）· `04-2awheel-sdk-cli-inspect.txt` + `05-2awheel-sdk-cli-hash.txt`
（内嵌 CLI 静态检查）· `99-wheels-final-sha256-list.txt`（31 包磁盘哈希）·
`99-2awheel-r2-final.txt`（汇总）· `wheelhouse/`（31 wheel + 31 `.headers`）·
`inspect/`（提取的 claude.exe + 版本文件，**未执行**）。