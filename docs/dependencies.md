# 依赖清单与一次性安装清单（docs/dependencies.md）

**版本核验日：2026-10-20（只读查询 `pypi.org` / `registry.npmjs.org` 索引；未安装任何包）。**
**状态：本清单为准安装清单；安装授权尚未批准（见 PowerShell 命令注释）。**

> 约定：确切版本 / 哈希均为**本次索引核验值**；**传递依赖闭包与逐包哈希在安装锁定时产生**
> （本批不联网安装，故不预先编造传递依赖哈希）。候选 C 供方、ADR-C1/C2/C3 保持 Accepted；
> 未通过实现测试项见 [adr-c1-c2-c3-decision-record.md](./../specs/001-single-repo-approval-loop/adr-c1-c2-c3-decision-record.md)。

## 1. 后端直接依赖（确切版本 + 完整 sha256 锚点）

| 包 | 锁定版本 | wheel（本机适用） | sha256（索引 `digests.sha256`，已核验） | 来源 | requires_python |
|---|---|---|---|---|---|
| fastapi | ==0.150.0 | `fastapi-0.150.0-py3-none-any.whl` | e566bc3f1347cfacf61f2f9ea1d7ab4576fbcff02eb9747c2807b8ced16d9e9a | PyPI | >=3.10 |
| uvicorn | ==0.54.0 | `uvicorn-0.54.0-py3-none-any.whl` | 505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf | PyPI | >=3.10 |
| pydantic | ==2.14.1 | `pydantic-2.14.1-py3-none-any.whl` | 9195d967ec791692a04438115466764fb8b9a27b31f14a760437694f40d6b454 | PyPI | >=3.10 |
| sqlalchemy | ==2.0.55 | `SQLAlchemy-2.0.55`（纯 py3-none-any wheel） | a13820f47eda53d603f56feaadeab9787d0110b7fcbe6ab2ff2415bd3ea31c79 | PyPI | ≥3.7（2.0 线；3.12 实测通过） |
| alembic | ==1.20.0 | `alembic-1.20.0-py3-none-any.whl` | 77eb101048d95f982c0353e9233404889dcd7a6fc244c107836c0e2fc9cf7d9d | PyPI | >=3.10 |

**开发依赖（dev；`requirements-dev.txt`）**：

| 包 | 锁定版本 | wheel | sha256 | 用途 |
|---|---|---|---|---|
| pytest | ==8.4.2 | `pytest-8.4.2-py3-none-any.whl` | 872f880de3fc3a5bdc88a11b39c9710c3497a547cfa9320bc3c5e62fbf272e79 | 测试 |
| httpx | ==0.28.1 | `httpx-0.28.1-py3-none-any.whl` | d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad | TestClient 依赖 |
| ruff | ==0.17.1 | `ruff-0.17.1-py3-none-win_amd64.whl` | 5df76f16580fab58d0f6c98a3ac254a4abceb7b2489b8b678335869cff77b3d7 | lint |

**后端首层传递依赖（本次核验；完整闭包与哈希在安装锁定，见 §3）**：
fastapi → `starlette>=0.46.0`、`pydantic>=2.9.0`、`typing-extensions>=4.8.0`、`typing-inspection>=0.4.2`、`annotated-doc>=0.0.2`、`opentelemetry-api>=1.44.0`；
uvicorn → `click`、`h11`（`typing-extensions<3.11` 分支在 3.12 不需）；
pydantic → `annotated-types`、`pydantic-core==2.50.1`、`typing-extensions>=4.16.0`、`typing-inspection>=0.4.4`；
sqlalchemy → `typing-extensions>=4.6.0`；
alembic → `SQLAlchemy>=2.0`、`Mako`、`typing-extensions>=4.12`（`tomli<3.11` 不需）；
pytest → `iniconfig`、`packaging`、`pluggy<2,>=1.5`、`pygments`、`colorama(win32)`；
httpx → `anyio`、`certifi`、`httpcore==1.*`、`idna`。

## 2. 前端直接依赖（确切版本 + 大版本差异标记）

| 包 | 现有约束（package.json） | 本次核对最新（2026-10-20） | 建议 |
|---|---|---|---|
| vue | `^3.4.0` | **3.5.44**（与约束兼容） | 保持 |
| vue-router | `^4.3.0` | 5.4.0（**主版本 5**） | **保守：保持 4.x**；升级待裁定 |
| vite | `^5.2.0` | 8.3.4（**主版本 8**） | **保守：保持 5.x**；升级待裁定 |
| @vitejs/plugin-vue | `^5.0.0` | 6.0.10（**主版本 6**） | **保守：保持 5.x**；升级待裁定 |
| typescript | `^5.4.0` | 7.0.2（**主版本 7**） | **保守：保持 5.x**；升级待裁定 |
| vue-tsc | `^2.0.0` | 3.3.13（**主版本 3**） | **保守：保持 2.x**；升级待裁定 |
| vitest | `^1.6.0` | 5.0.5（**主版本 5**） | **保守：保持 1.x**；升级待裁定 |

- 来源：`registry.npmjs.org`；完整性：`package-lock.json` 内 `integrity`（SHA-512）由 `npm install` 生成、`npm ci` 强制校验。
- **保守策略**：复用现有 package.json 的 caret 主版本，避免大版本破坏；确切小版本由 npm 在安装时按 `^` 解析并锁入 `package-lock.json`（**本批不预写未核验的小版本号**）。
- 已排除：不引入 UI 组件库、状态管理库、axios（用原生 fetch）等无必要依赖（§6「避免无必要依赖」）。

## 3. 传递依赖锁定方式 + 完整性校验机制

| 侧 | 锁定方式 | 完整性机制 |
|---|---|---|
| 后端 | 安装授权时：`pip install --dry-run --report=report.json -r requirements.txt`（解析**完整闭包**，产出逐包 `==版本 + sha256`）→ 转成 `requirements.lock` → `pip install --require-hashes -r requirements.lock` | PyPI 索引 `digests.sha256` + `--require-hashes`（逐包哈希强制） |
| 前端 | `npm install` 生成 `package-lock.json`（每包 `resolved` 官方 URL + `integrity` SHA-512）；之后 `npm ci` 严格按 lock 安装 | npm lock 的 `integrity`（SHA-512） |

> 直接依赖的 sha256 锚点已在 §1 列出；**传递依赖的逐包哈希在本批锁定前属「待确认」**（不编造）。

## 4. 安装范围

- 后端：项目独立 venv `backend/.venv`（`--copies`，Python **3.12.10**，不启用系统 site-packages）；仅 `backend/.venv` 与 `backend/**` 受安装影响。
- 前端：`frontend/node_modules/` + `frontend/package-lock.json`。
- 不写入系统 Python、不写入任何真实业务仓库。

## 5. Windows PowerShell 安装命令（**待一次性安装授权后执行**）

```powershell
# 以仓库根 D:\wo\code\ADLL\ADLL 为工作目录；PowerShell 5.1+
$ErrorActionPreference = "Stop"
$py = "D:\wo\python\Python312\python.exe"   # 以本机实际 3.12 解释器路径为准（D-PY 裁定）

# 1) 后端独立 venv + 安装（首次运行；生成 backend/.venv）
Push-Location backend
& $py -m venv .venv --copies
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
Pop-Location

# 2) 前端安装 + 构建（node v24）
Push-Location frontend
npm install       # 首次生成 package-lock.json；之后可改用 npm ci
npm run build     # vue-tsc 类型检查 + vite 构建
Pop-Location
```

## 6. 安装后验证

```powershell
# 后端导入验证
& "backend\.venv\Scripts\python.exe" -c "import fastapi,sqlalchemy,alembic;print('OK',fastapi.__version__,sqlalchemy.__version__)"

# 后端 pytest（健康检查测试）
Push-Location backend
& ".\.venv\Scripts\python.exe" -m pytest tests -q
Pop-Location

# 后端 /api/health（起服务后另开终端）
# & "backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
# Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health   # 期望 {"status":"ok",...}

# 前端（本批无 Vitest 用例，故用 build 作为前端构建验证；vitest 待测试任务补充）
# npm run build 已在上一步执行
```

## 7. 版本冲突 / 安全风险 / 待确认（如实声明）

1. **SQLAlchemy 版本（已解决）**：保留 pyproject `>=2.0,<2.1` 约束，选定 2.0.x 最新稳定 **2.0.55**（已核验并锁入 `requirements.txt`/`requirements.lock`）；不升级 2.1.5。
2. **pytest 版本（已解决）**：保留 8.x 约束，选定 **8.4.2**（已核验并锁入 `requirements-dev.txt`/`requirements.lock`）；不升级 9.1.1。
3. **前端大版本漂移**：vue-router(5)/vite(8)/typescript(7)/vue-tsc(3)/vitest(5)/@vitejs/plugin-vue(6) 均越过现有 caret 主版本。**建议保守保持现有主版本**；是否升级为**待裁定**（升级可能引入破坏性变更，未经本批验证）。
4. **fastapi 新增首层依赖**：0.150.0 引入 `opentelemetry-api` 与 `annotated-doc`（据其 `requires_dist`）——**如实登记**，不视为安全风险，但不在「最小依赖」预期内。
5. **uvicorn `[standard]` extra**：pyproject 原写 `uvicorn[standard]`，会引入 httptools/websockets/watchfiles/pyyaml/python-dotenv（uvloop 非 win）。`requirements.txt` 锁**纯 `uvicorn`**（仅 click+h11），更精简——建议 pyproject 同步去掉 extra——**待裁定**。
6. **需执行"安装脚本"的依赖：无**（§1/§2 全部为纯 wheel / npm tarball；无 post-install 脚本、无源码编译）。
7. **传递依赖逐包哈希与完整闭包**：安装锁定前属**待确认**，本清单不预编造。

## 8. 明确不构成

- 本清单**不授权安装**；安装须另获一次性授权（届时对本清单逐项核验）。
- 不修改 spec.md、宪章、AGENTS.md、CLAUDE.md、ADLL-Knowledge、历史实验原始证据。
- 候选 C 口径不因本清单变化：SDK 阶段 3 **仍暂停**；Messages Smoke PASS 仅代表连通性；
  候选 C 的安全/审计/权限验证**不取消**。

## 9. 实际安装与验证结果（2026-10-20）

> 本批已获**一次性安装授权**并完成（§8「不授权安装」态已被 2026-10-20 授权取代）。

- **解释器**：`D:\wo\python\Python312\python.exe` → **3.12.10**（实测存在）；后端 venv `backend/.venv`（`--copies`，pip 25.0.1，未升级）。
- **锁定**：`backend/requirements.lock`（**29 项**，全部 `==ver --hash=sha256`，仅 wheel）；`--require-hashes --only-binary=:all:` 安装成功；**`pip check` = No broken requirements**。
- **pytest**：`1 passed`，exit 0（`tests/test_health.py`）；1 条 `StarletteDeprecationWarning`（starlette 1.9.0 的 TestClient 弃用 httpx、建议 httpx2）——**非失败**，登记为后续维护项。
- **FastAPI**：`uvicorn app.main:app --host 127.0.0.1:8000` → `GET /api/health` = **200** `{"status":"ok","app":"ADLL"}`；`GET /api/health/unknown` = **404**（不崩溃）；仅绑定 127.0.0.1。
- **前端 registry**：`npm config get registry` = **`http://registry.npmmirror.com`**（本机既有全局配置：HTTP 镜像、非官方）。据此生成的 lock 全部解析到 npmmirror → **已改用 `--registry=https://registry.npmjs.org` 重新生成**；最终 `package-lock.json` resolved **160/160 = `registry.npmjs.org`（0 镜像）**，integrity 齐全。
  - 含安装脚本依赖：**`esbuild`、`fsevents`**（`--ignore-scripts` 跳过脚本；esbuild 二进制经 optionalDependencies 提供，构建正常；fsevents 仅 macOS 且本机不装）。未作 peer 定向修复（`npm ci` 无 peer 冲突）。
  - `npm ci --ignore-scripts` → **added 113 packages**，exit 0。
  - `npm run build`（vue-tsc + vite 5.4.21）→ **exit 0**，`dist/` 产出。
  - `npx vite preview --host 127.0.0.1:4173` → `GET /`=**200**（返回 index.html），资产 200。
- **前端健康检查请求链路**：**尚未实现**（本批仅静态页面 + 构建；`api/client.ts` 为骨架未接线）——正常/失败行为验证**不在本批范围**，留待 Phase 3+。
- **未执行**：真实 AI 调用、业务仓库读写、DASHSCOPE_API_KEY、T006–T011、git commit/push；未改 spec/宪章/AGENTS/CLAUDE。