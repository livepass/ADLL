# ADLL

单仓库任务与 AI 方案审批闭环：链接本地 Git 仓库 → 提交正式需求 → 受控生成方案 →
人工审批 → 反馈与再生成。默认 **fail-closed**：未显式启用时不会向外部 AI 发送任何数据。

## 组成

```text
backend/    FastAPI + SQLAlchemy 2.0 + Alembic（SQLite）
frontend/   Vue 3 + Vite + TypeScript
specs/      需求、契约、S1–S15 验证矩阵与证据记录
docs/       依赖与调研文档
```

## 环境要求

- Python 3.11+（CI 与验证使用 3.12）
- Node.js 20+（验证使用 22）
- Git 2.30+
- Windows 专属：受限 worker 的 DACL/Job Object 测试只在 Windows 运行，其他平台自动跳过

## 后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install --require-hashes -r requirements.lock   # Windows
# .venv/bin/pip install --require-hashes -r requirements.lock      # Linux/macOS

cp .env.example .env        # 按需填写；不提交 .env
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload
```

依赖锁定：`requirements.lock` 含 SHA-256，覆盖运行时与开发依赖；
`requirements.txt` / `requirements-dev.txt` 为可读的顶层清单。

## 前端

```bash
cd frontend
npm ci
npm test
npm run build
npm run dev      # 本地开发
```

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm test
```

Windows 上若临时目录文件数超过安全删除阈值，可用
`CODEBUDDY_SAFE_DELETE_ENABLED=0` 仅对测试进程关闭回收站守卫。

## 安全边界（默认值）

- 真实 AI 发送默认关闭（`ADLL_REAL_AI_ENABLED=false`），无凭据时不启动。
- 出站授权必须显式给出接收端点与源码路径白名单；空范围**不代表**全部源码。
- 发送前持久化请求摘要与载荷清单；审计按 `prepared / possibly_sent /
  confirmed_sent / not_sent` 记录，不虚构网络事实。
- 方案只有核验 `verified` 后才可进入审批。

环境变量见 `backend/.env.example` 与 `frontend/.env.example`。

## 许可证

**尚未选择**。在人工确认许可证之前，本仓库不授予任何明示或默示的使用许可。
