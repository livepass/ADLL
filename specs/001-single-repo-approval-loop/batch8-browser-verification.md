# 批 8 浏览器离线验收记录

**Date**: 2026-10-21
**方式**: Edge headless（`msedge.exe --headless=new`）+ Chrome DevTools Protocol，
由 `backend/scripts/browser_e2e.py` 操作真实页面；数据全部经真实 FastAPI HTTP 接口。
**后端**: `ADLL_TESTING=1`，Mock 生成；`ADLL_REAL_AI_ENABLED=0`；
独立临时 DB；授权根为合成仓库父目录。
**前端**: `npm run dev`（Vite，`/api` 代理到 `127.0.0.1:8000`）。
**边界**: 无真实百炼请求、无 `DASHSCOPE_API_KEY`、无真实业务仓库；测试口令仅用于临时实例。

## 1. 环境与命令（testing 模式）

```text
# 合成仓库（临时）
backend/.browser-test/repo   → commit 3cfbfba6a9c8c8927b75351e116912e81ade5ddc

# 迁移（临时 DB）
ADLL_DATABASE_URL=sqlite:///D:/wo/code/ADLL/ADLL/backend/.browser-test/test.db \
  python -m alembic -c alembic.ini upgrade head

# 后端
ADLL_TESTING=1 ADLL_REAL_AI_ENABLED=0 \
ADLL_DATABASE_URL=sqlite:///D:/wo/code/ADLL/ADLL/backend/.browser-test/test.db \
ADLL_ADMIN_PASSWORD=<临时测试口令> \
ADLL_AUTHORIZED_ROOTS=D:/wo/code/ADLL/ADLL/backend/.browser-test \
ADLL_COOKIE_SECURE=0 \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173

# 浏览器
backend/.venv/Scripts/python.exe scripts/browser_e2e.py \
  --base-url http://127.0.0.1:5173 \
  --repo D:/wo/code/ADLL/ADLL/backend/.browser-test/repo \
  --password <临时测试口令> \
  --db backend/.browser-test/test.db \
  --out-dir backend/.browser-test/screens2
```

## 2. testing 模式实际步骤与结果（全部 PASS）

| 步骤 | 实际结果 |
|---|---|
| login | 登录页 → 工作台；会话 Cookie HttpOnly，CSRF 仅内存 |
| link_repo | 显示完整 SHA `3cfbfba6a9c8c8927b75351e116912e81ade5ddc`、object_format、基准 |
| create_task | 跳转 `/tasks/1` |
| save_requirement | 正式需求 v1 保存 |
| create_authorization | receiver/数据类型/范围创建成功（approved） |
| 403_outbound_denied_feedback | 第二页面撤销授权后，原页面仍显示有效 → 点击生成；服务端 403，页面显示 `outbound_denied` |
| 423_baseline_unavailable_feedback | 临时 DB 故障注入 `available=0` 后点击生成；页面显示 `baseline_unavailable`（HTTP 423） |
| mock_generation | 页面明确标记“测试/离线模式”；生成 `completed`；provider 显示 `mock（合成，非真实）`；usage 为合成值，费用 `unknown` 不显示金额 |
| 409_approval_exists_feedback | 第二页面先批准；原页面过期状态下点击批准；服务端 409，页面显示 `approval_exists` |
| approve | 重新加载后批准成功；显示“已批准且有效” |
| reload_restores_state | 刷新后任务、需求、方案、审批状态恢复 |
| requirement_change_invalidates_approval | 保存 v2 需求后旧批准显示“曾批准但已失效” |
| revoke_authorization | 撤销成功（revoked） |
| 401_redirects_to_login | 清除 Cookie 后访问任务页 → `/login` |

截图（已归档到 `batch8-evidence/`）：
`01-dashboard.png`、`02-task.png`、`03-403.png`、`04-423.png`、`05-409.png`、
`06-approved.png`、`07-invalidated.png`。

## 3. 生产模式 503 页面反馈

后端切换为 `ADLL_TESTING=0 ADLL_REAL_AI_ENABLED=0`（独立 `prod.db`，已迁移），
前端不变。实际步骤（全 PASS）：

| 步骤 | 实际结果 |
|---|---|
| login / link_repo / create_task / save_requirement / create_authorization | 正常 |
| ui_blocks_real_generation | 页面显示“生产模式：真实 AI 发送默认关闭（fail-closed）”；“发起真实生成”按钮默认禁用并显示原因 |
| 503_ai_disabled_feedback | 故障注入：移除 DOM `disabled` 后点击 → 服务端 503，页面显示 `ai_disabled` |

截图：`10-production-disabled.png`、`11-503.png`。

## 4. 失败点与修正（如实记录）

1. 首次启动后端只启动 uvicorn、未执行 Alembic：登录报 `internal_error`（`no such table: user_sessions`）。
   修正：对临时 DB 执行 `alembic upgrade head` 后重启；未改生产代码。
2. 授权范围文本框选择器按标签文本匹配失败：改为按 placeholder `src/app.py` 定位。
3. 创建任务按钮在 `busy` 未复位时点击返回 `disabled`：测试脚本增加“按钮可用”等待后通过。
4. 生产 503：UI 默认禁用按钮（fail-closed），因此通过临时移除 DOM disabled 触发一次真实
   HTTP 请求以验证页面错误反馈；这属于故障注入，不代表生产 UI 允许点击。

## 5. 未覆盖

- 未在真实浏览器中验证 SSE（本实现无伪造 SSE，使用轮询；页面已标注）。
- 未验证真实模型输出、真实网络、真实计费。
- 未做跨浏览器（仅 Edge Chromium）；未做移动端布局验收。