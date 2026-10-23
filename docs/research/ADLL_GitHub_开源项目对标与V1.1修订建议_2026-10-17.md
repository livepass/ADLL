# ADLL 开源项目对标与技术借鉴报告

- 调研日期：2026-10-17
- 适用阶段：ADLL V1.1 需求定义之前
- 项目既定约束：Python + FastAPI + Pydantic；Vue 3 + TypeScript + Vite；源码与项目文档使用项目 Git；独立 Obsidian Vault + 私有 Git；跨 Agent 使用 AGENTS.md + Skills；人工审批与真实执行权限隔离。
- 调研方法：阅读 GitHub 仓库 README、许可证、相关配置/代码文件和官方技术文档；使用 GitHub 提交查询核对部分项目的近期提交情况。**未克隆运行、未开展安全审计，也未完成 Windows 实机兼容性或性能基准测试。**
- 注意：本报告是技术调研和需求修订建议，不等同于用户对库选型、需求或实施的最终审批。**未修改任何用户本地仓库或 Obsidian Vault。**

## 一、核心结论

1. **ADLL 的区别不在通用可视化 Agent 控制台，而在开发—审批—真实源码知识—教学—实践的可信闭环。** OpenHands 当前的 Agent Canvas 已是支持 Claude Code、Codex 等的可视化多 Agent 控制台，因此不可将“有个网页驱动 Agent”本身视为差异化能力。
2. **不建议 V1.1 直接 Fork 或整体安装 OpenHands / Dify 来替代 ADLL。** 它们已有更大范围的系统设计、不同的前端和运行时约束。可借鉴交互与执行器契约；但继续使用已批准的 FastAPI + Vue3，减少架构偏航。
3. **最有价值的直接技术候选是 Claude Agent SDK for Python**，用于真实的方案生成与流式结果。其运行凭据、成本、Windows 兼容性及权限策略必须在 `/speckit-plan` 之前先做受控可行性验证；现在不能提前写死选型。
4. **不必 V1.1 就集成 LangGraph。** 其 interrupt/checkpoint/human-in-the-loop 机制值得借鉴；对于“单用户、一个 Agent、一次生成—审核—批准”流程，应用侧状态机与持久化可能更简单。未来多阶段可恢复工作流再评估引入。
5. **V1.1 要更聚焦：先做单仓库、单任务、真实只读方案生成、版本化审核与人工批准。** UI 对比、复杂项目库管理、批量任务和知识同步等不要提前实现。
6. **严禁把提示词、`allowed_tools` 或 UI 按钮置灰当作安全边界。** Claude Agent SDK 文档明确指出 `allowed_tools` 仅表示自动批准的工具，不会自动禁用其他工具。对写文件、执行命令、跨目录读写必须有工具拒绝规则、隔离进程/工作区和应用后端约束。

## 二、候选项目对照

| 项目 | 核查到的特性（来源见下） | 许可证（以核查日官方仓库为准） | 对 ADLL 的价值 | 现阶段建议 |
|---|---|---|---|---|
| [OpenHands Agent Canvas](https://github.com/OpenHands/OpenHands) | 可视化工程 Agent 控制台；支持 Claude Code、Codex 等后端；可选择本地/容器/远端运行；前端使用 React | MIT | 任务 UI、执行日志、多 Agent 适配、容器与权限边界 | **重点借鉴，不整体 Fork** |
| [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk) | Python/TypeScript/REST；Agent Server、工作区、事件、会话与工具；支持隔离执行 | MIT | 执行器抽象、Agent Server 设计 | V1.2 重点候选；V1.1 观察 |
| [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python) | `query`、交互式 client、流式输出、Hooks、权限回调、工具策略 | SDK 仓库 MIT；**使用受 Anthropic 商业条款约束** | 当前使用 Claude Code，最直接的 Agent 接入候选 | **V1.1 优先做受控可行性测试** |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | 以软件工程任务修复为目标的 Agent；官方已推荐优先使用 mini-swe-agent | MIT | 了解代码任务的轨迹与测试评估 | 参考思路，不优先采用原框架 |
| [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent) | 简化的 Python Agent，基本以 Bash 执行和线性历史为核心；多种执行环境 | MIT | Agent 轨迹、极简模型、评估方法 | 适合研读；不适合作为 V1.1 无执行权限分析器直接集成 |
| [Aider](https://github.com/Aider-AI/aider) | Git 代码库上下文，`ask`/`code`/`architect` 等模式 | Apache-2.0 | 明确区分“讨论/方案”和“改代码” | **借鉴模式边界**；不直接使用 `architect` 作为只读审批 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 图状态、checkpoint、`interrupt()`、恢复与人机协作 | MIT（核心仓库） | 状态机、恢复、审批流程设计 | **借鉴；暂不做 V1.1 必选依赖** |
| [Dify](https://github.com/langgenius/dify) | 可视化 AI 工作流、运行状态、节点编排；前端采用 React/Next 生态，后端代码依赖 Flask 等 | **基于 Apache 2.0 的自定义附加条件许可证** | 可视化交互与错误展示 | 参考 UI，不直接复制前端源码；如复用必须复核许可证 |
| [Obsidian Git](https://github.com/Vinzent03/obsidian-git) | Vault 的 Git 版本历史、diff、手动或定时 commit/sync | MIT | V1.3 的长期笔记版本管理 | V1.3 使用候选；V1.1 暂不接入 |

### 特别需要纠正的印象

- OpenHands 目前的主要可视化入口是 **Agent Canvas**；[`OpenHands/OpenHands`](https://github.com/OpenHands/OpenHands) 的 README 明确指出支持 Claude Code 和 ACP 兼容 Agent。其当前 [`package.json`](https://github.com/OpenHands/OpenHands/blob/main/package.json) 含 React 依赖，直接采用会与既定 Vue3 技术栈冲突。
- 原链接 `All-Hands-AI/OpenHands` 实际已重定向到 `OpenHands/OpenHands`；`denolehov/obsidian-git` 已转移到 `Vinzent03/obsidian-git`，建议将新地址写入项目调研资料。
- SWE-agent 官方 README 明确建议新项目优先看 mini-SWE-agent：[`SWE-agent/SWE-agent`](https://github.com/SWE-agent/SWE-agent)。但 mini-SWE-agent 依赖 Bash 核心能力，与 ADLL V1.1 的“只读方案生成、禁止执行”目标不吻合。
- Aider 的 `ask` 模式声明不修改代码；**`architect` 模式仍会驱动编辑器实际修改文件**，不能将其直接等同于“人工批准前只生成方案”。参见 [Aider 模式说明](https://github.com/Aider-AI/aider/blob/main/aider/website/docs/usage/modes.md)。
- Dify 源码核查：[`web/package.json`](https://github.com/langgenius/dify/blob/main/web/package.json)、[`api/pyproject.toml`](https://github.com/langgenius/dify/blob/main/api/pyproject.toml)。其许可证规定部分多租户使用和前端标识等附加条件，参见 [正式 LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE)。

## 三、维护情况（仅作为快照，不代表全面审计）

通过 GitHub 提交查询找到的最近提交，截止 2026-10-17；具体日期存在索引与时区差异，后续若确定直接依赖应重新核对版本发布和安全公告。

| 仓库 | 查询到的最近提交（UTC） | 参考链接 |
|---|---|---|
| OpenHands/OpenHands | 2026-10-16 | [0452907](https://github.com/OpenHands/OpenHands/commit/045290739f0af2ae4cc89d2a209c6bd930bb81ee) |
| anthropics/claude-agent-sdk-python | 2026-10-16 | [f93e29c](https://github.com/anthropics/claude-agent-sdk-python/commit/f93e29cc951cd5fddcaaed9f3c49c3c38dedd6ab) |
| langchain-ai/langgraph | 2026-10-16 | [41c9c22](https://github.com/langchain-ai/langgraph/commit/41c9c22fdc83d68a2859d0c9a2b627c8615a792f) |
| langgenius/dify | 2026-10-17 | [a5a937a](https://github.com/langgenius/dify/commit/a5a937a01d11985ca51eb60c204e84dc88239827) |
| Vinzent03/obsidian-git | 2026-10-14 | [af0a934](https://github.com/Vinzent03/obsidian-git/commit/af0a934c24d5b57bb0996c917a2d77849ac7136d) |
| SWE-agent/mini-swe-agent | 2026-09-03 | [04d809c](https://github.com/SWE-agent/mini-swe-agent/commit/04d809ceab9df28f9adaed044884180159172930) |
| SWE-agent/SWE-agent | 2026-07-16 | [3ea751c](https://github.com/SWE-agent/SWE-agent/commit/3ea751c087f32b16e039a2233dd6eefecef325d5) |
| Aider-AI/aider | 2026-05-22 | [5dc9490](https://github.com/Aider-AI/aider/commit/5dc9490bb35f9729ef2c95d00a19ccd30c26339c) |

不能只用 Star 数与“最近提交日期”评价项目成熟度。正式依赖选型还需核对发行版本、兼容范围、安全公告、维护者响应和破坏性变更。

## 四、ADLL V1.1 的技术取舍

### 4.1 三种路线比较

| 路线 | 能直接复用什么 | 最大代价 | 结论 |
|---|---|---|---|
| A. 自研 FastAPI + Vue3，接入 Claude Agent SDK | 保留既定架构和审批域模型；只复用 Agent 引擎 | 需要自行实现版本审批、任务状态和 UI | **优先路线** |
| B. Fork OpenHands Agent Canvas | 可视化控制台和多 Agent 入口已经存在 | 当前 React UI、多仓库体系与 ADLL 独有学习域难以直接契合 | 不建议在 V1.1 切换 |
| C. Dify 作为工作流核心 | 可视化工作流与节点机制 | 系统庞大、技术栈不同、许可证额外限制；审批版本域仍需开发 | 不建议 |

**推荐的未来实现逻辑图（仅供 `/speckit-plan` 比选，不是已批准架构详细设计）：**

```text
ADLL Vue3 可视化界面
    |
    v
FastAPI API / 应用服务（任务、方案、人工审批、审计）
    |                               |
    |                         应用运行时持久化
    v
AgentAdapter 抽象接口
    |
    +-- Claude Agent SDK（V1.1 候选）
    +-- 其他 Agent（未来）
    |
只读、受限的项目分析工作区（绑定 Git commit）

[独立 ADLL-Knowledge Vault] —— V1.3 才接入
```

**不主张直接在方案生成阶段引入 LangGraph。** 仅当用户审批跨多个异步步骤、复杂分支、长时间恢复等需求出现并证明手工状态机成本显著增加时，再评估。LangGraph 官方文档要求 `interrupt()` 配合 checkpointer 和 thread ID；其恢复机制不自动替代 ADLL 的批准版本校验和后端权限控制。

### 4.2 Claude Agent SDK 的安全与成本约束

1. [官方 SDK README](https://github.com/anthropics/claude-agent-sdk-python/blob/main/README.md) 明确：`allowed_tools` 是工具自动批准表，**不等于工具禁用表**；未列出的工具可能交给权限模式或回调决定。禁用工具须使用 deny 规则（`disallowed_tools`）并验证具体生效顺序。参见 [官方权限说明](https://code.claude.com/docs/en/agent-sdk/permissions)。
2. V1.1 的 Agent 应只接触已授权的分析副本，避免在目标 Git 仓库本体里运行可写工具；需要控制工作目录、默认加载的规则文件、敏感文件、符号链接、外部目录与子进程访问。**工具级禁令不等价于进程/文件系统隔离**。
3. 目标仓库里的 README、注释、`AGENTS.md`、`CLAUDE.md` 等内容可能含有提示词指令；在分析目标项目时应当把它们视作**待分析的数据**，不能自动提升为 ADLL 的控制规则。尽量避免让 Agent 在不可信目录里自动加载该项目的执行规则。
4. 应核对 Claude Agent SDK 的**认证和计费**，不能假设已安装/登录 Claude Code 就可无成本或无额外授权地用第三方应用自动调起 SDK。官方 [SDK README 的 Terms](https://github.com/anthropics/claude-agent-sdk-python/blob/main/README.md) 说明使用受 Anthropic 商业条款约束；[Claude API 身份验证说明](https://platform.claude.com/docs/en/manage-claude/authentication) 给出 Console API 凭据方式。
5. FastAPI 应负责审批和任务管理的业务边界，Agent 不直接获得“批准方案”的数据库写入能力。即使 Agent 工具越权，也不能操作正式审批数据。

### 4.3 LangGraph 对 ADLL 的可借鉴设计

- 人工批准是一段业务状态变更，而不是模型说“已批准”。
- 生成与审批的上下文需要持久化，以便应用重启后恢复。
- 拒绝、修改、重试均应产生可审计事件。
- 如果未来使用 `interrupt()`，要注意 [LangGraph 文档](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py) 指出恢复时节点会从头重跑；审批前后的副作用必须幂等或外移。此问题在 V1.2 实际执行时尤其重要。

## 五、修订 ADLL V1.1 需求范围的建议

### 5.1 维持为“单仓库、单 Agent、无代码执行”的最小切片

| 需求项 | 原设想 | 本轮修订建议 |
|---|---|---|
| 项目关联 | 选择项目、查看状态 | V1.1 仅关联**一个**由用户授权的现有 Git 仓库；不建立复杂项目中心 |
| Git 基准 | 展示当前分支/Commit | 方案与审批必须绑定**完整 commit SHA**；未提交/未跟踪的更改作为显式异常或要求用户选择是否以干净 commit 分析，不能静默混入 |
| Agent 集成 | 调用真实 Claude Code | 保留真实调用验收；通过 SDK/CLI 适配器选型前验证本机可行性、授权与费用；测试 Mock 不冒充产品功能 |
| AI 方案只读性 | 提示不准修改 | 必须有工具权限 + 受控分析工作区 + 运行前后文件完整性证据；**只靠 system prompt 不合格** |
| 用户修改方案 | 可以编辑、批注、diff | V1.1 优先实现明确反馈、生成新版、保留旧版；复杂可视化 diff 与行级批注可延后 |
| 审批一致性 | 方案版本+哈希 | 同时绑定任务需求版本、分析 commit SHA、方案哈希，批准后不可变；变更将批准状态置为待重新审批 |
| 失败恢复 | 失败可重试 | 显示任务执行 ID、失败原因、可重试动作；重复请求不得导致重复批准或重复版本覆盖 |
| 多 Agent | 适配多家后端 | V1.1 只实现一个适配器；接口可扩展但不要求第二家实例 |
| LangGraph | 候选工作流框架 | 不预先规定，留到技术设计用复杂度判断 |
| Obsidian | Vault 集成 | 保持在 V1.3；V1.1 不访问私有 Vault |

### 5.2 V1.1 验收门槛（建议新补）

- **安全性门禁**：以恶意或非预期仓库内容测试，无法通过源文件内指令诱导越权写文件/执行危险命令；若实现不可信来源自动加载，必须作为阻断缺陷处理。
- **只读完整性门禁**：方案生成之前和之后，对目标仓库文件/工作区状态核对。Git status 只能观察部分变化；结合纳入监控范围的文件校验或只读挂载，说明未检测范围，不可伪称绝对不变。
- **审批失效门禁**：方案、需求验收条件、批准引用的 Git 基准变动后，执行状态不得继续显示“当前可批准/可执行”。
- **API/成本门禁**：明确 SDK 调用所需认证方式，失败/限额/费用信息可提示，V1.1 不应依赖从未验证的 CLI 登录复用假设。
- **易用性门禁**：用户通过网页完成关联→需求→方案→审核→批准；日志、版本摘要、失败原因可查看。
- **恢复门禁**：页面刷新与重启后，任务、审批、历史仍可恢复；失败重试不制造重复的批准记录。

### 5.3 保留到 V1.2 / V1.3

- V1.2：受批准版本驱动的真正编码与测试、Worktree/隔离执行、Git 变更展示、恢复机制。
- V1.3：源码知识卡、Obsidian Vault 写入、教学问答、IDE 实践与掌握证据。
- 以后：多 Agent 调度、多人协作、跨设备、复杂工作流。

## 六、下一步执行顺序

1. **人工审阅本报告**：确认保留现有 FastAPI + Vue3、自建审批核心、只读真实 Claude 集成作为候选，不引入整套 OpenHands/Dify。
2. **修订 `/speckit-specify` 的输入**：把第五节的限制、验收与不做范围写入需求；不要在 specify 阶段把 Claude Agent SDK / SQLite / LangGraph 定为最终实现方案。
3. 生成 `spec.md` 后先审阅，再 `/speckit-clarify` 对授权目录、分析快照、脏工作区、审批重入、真实 Agent 费用与认证等进行澄清。
4. **在 `/speckit-plan` 做受控技术验证**：Windows + Claude Code、SDK 认证、只读权限、任务超时与流式返回；形成 ADR，比较 SDK 与 CLI/其他可用接入方式。
5. 经批准再 `/speckit-tasks`，并且用户确认后才实施。**不在本次调研中创建/修改用户任何本地仓库文件。**

## 七、原始资料与许可证入口

1. [OpenHands Agent Canvas README](https://github.com/OpenHands/OpenHands/blob/main/README.md) · [Source/package.json](https://github.com/OpenHands/OpenHands/blob/main/package.json) · [MIT](https://github.com/OpenHands/OpenHands/blob/main/LICENSE)
2. [OpenHands Software Agent SDK README](https://github.com/OpenHands/software-agent-sdk/blob/main/README.md) · [MIT](https://github.com/OpenHands/software-agent-sdk/blob/main/LICENSE)
3. [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python/blob/main/README.md) · [Permissions](https://code.claude.com/docs/en/agent-sdk/permissions) · [Repository LICENSE](https://github.com/anthropics/claude-agent-sdk-python/blob/main/LICENSE) · [SDK Terms](https://github.com/anthropics/claude-agent-sdk-python#license-and-terms)
4. [SWE-agent README](https://github.com/SWE-agent/SWE-agent) · [mini-SWE-agent README](https://github.com/SWE-agent/mini-swe-agent) · [mini license](https://github.com/SWE-agent/mini-swe-agent/blob/main/LICENSE.md)
5. [Aider README](https://github.com/Aider-AI/aider) · [Chat modes](https://github.com/Aider-AI/aider/blob/main/aider/website/docs/usage/modes.md) · [Apache-2.0](https://github.com/Aider-AI/aider/blob/main/LICENSE.txt)
6. [LangGraph README](https://github.com/langchain-ai/langgraph) · [interrupt implementation](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py) · [License](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)
7. [Dify README](https://github.com/langgenius/dify) · [License](https://github.com/langgenius/dify/blob/main/LICENSE) · [Web configuration](https://github.com/langgenius/dify/blob/main/web/package.json) · [API configuration](https://github.com/langgenius/dify/blob/main/api/pyproject.toml)
8. [Obsidian Git README](https://github.com/Vinzent03/obsidian-git) · [Features](https://github.com/Vinzent03/obsidian-git/blob/master/docs/Features.md) · [MIT](https://github.com/Vinzent03/obsidian-git/blob/master/LICENSE)

> 版权说明：本报告只引用项目与官方文档链接并作归纳、技术评价，没有复制第三方代码；直接复用任何库或代码时仍需逐项核实许可和版本。
