# S9 执行身份与网络隔离架构裁定

日期：2026-10-23。基线：`cb3a40e73159e6c6743d0f21890370102c60e2cb`。
宪章：v1.2.0 RATIFIED。裁定记录版本：1.0。

## 1. 人工决定与授权边界

用户在审阅本次架构评估后回复「可以」，随后明确选择「先完成文档，部署位置待定」。
批准的路线为：**独立 Windows Worker VM + 默认拒绝的专用网络 + 固定目标出口**。
此批准关联本次会话中基于上述 commit 的架构评估，不冒充对本文件新增细节的逐项批准。

本文件是 S9 后续架构与验收的权威补充，取代旧部署说明中专用账户直接配合
`block_all + allow_dashscope` 即可落地的结论。历史测试记录继续保留其历史含义。
部署位置、虚拟化产品、镜像、出口实现、具体地址、路径及凭据存储均待技术规划确定。
当前只完成文档；不进入编码、安装、账户/ACL/防火墙变更或真实发送阶段。
详细 plan、契约及任务拆解须继续按 Spec Kit 审批阶段推进；正式执行审批应绑定
最终方案版本与内容摘要，不能以本次路线批准代替。

## 2. 已核实事实

- `win32.py::create_restricted_token` 从父进程令牌派生，未改变 TokenUser。
  `factory.py`/`WorkerAgentAdapter` 中的配置 SID 未接入进程创建机制。
- `spawn_restricted` 未挂起创建，先运行子进程再加入 Job 和检查受限令牌；
  未复核实际子进程 TokenUser。Job 分配失败分支缺少显式终止未纳管进程。
- `sandbox.py` 的授权包含父账户 SID，不能直接复用为独立账户权限方案；
  探针实例与实际执行实例分离，前者不能替代后者的身份验证。
- Windows Firewall 显式 Block 优先于冲突 Allow；出站规则同样适用。
  创建顺序及更窄 Allow 均不能使旧规则组合正常放行。
- `network_boundary.evaluate` 拒绝同主体任何 Allow，原因名
  `allow_rule_overrides_block` 不符合 Windows Firewall 优先级。
- 采集器缺少实际进程身份、完整有效策略及可信拒绝观测；覆盖字段为 False。
  原生产链路可以安全拒绝，但没有可达的真实放行路径。
- `outbound.begin_attempt` 已提交 prepared 审计；但 GenerationRequest 未携带
  attempt 和持久化 request_digest，适配器自行重算，未形成直接审计绑定。
- `sent.marker` 在网络调用前创建，只能支持可能发送判断；现有 response_digest
  为解析文本摘要，不是服务商原始响应字节摘要。

源码定位：`backend/app/isolation/{win32,sandbox,worker_main}.py`、
`backend/app/agents/{base,worker,factory}.py`、
`backend/app/services/{network_boundary,outbound,generation_service,verification}.py`。

只读环境检查：Windows 11 家庭中文版 build 22000，64 位，内存约 15.8 GiB，
检查时空闲约 3.4 GiB；三个宿主 Firewall Profile 均启用且默认出站 Allow。
BFE/MpsSvc 运行，HypervisorPresent=True；部分 CPU 虚拟化字段为 False，
不能据此推断硬件不支持，亦不能据现有服务认定完整 Hyper-V 可部署。
未发现 ADLL 前缀本地账户；登录权、凭据和完整存储容量未核实。
受限查询曾拒绝 CIM 读取，随后仅通过获准的只读查询取得上述系统信息。

## 3. 路线比较与裁定

| 路线 | 依赖、成本及局限 | 当前裁定 |
|---|---|---|
| 专用账户 + 原 Firewall Block/Allow | 规则冲突，无法同时满足可达性和隔离 | NO-GO |
| 专用账户 + 专门 WFP 策略 + 受控出口 | 可按用户在 ALE v4/v6 层过滤；需要策略服务、事件采集、回环和系统服务代发验证；资源低但安全维护成本高 | 候选，未验证，不首选 |
| 独立 Windows Worker VM + 专用网络 + 固定出口 | 保留 TokenUser；默认拒绝仅影响专用环境；增加虚拟化、许可、镜像与出口维护 | 路线获批；部署 NO-GO |
| 当前本机 WSL2 + Hyper-V Firewall | 该防火墙从 Windows 11 22H2 起提供；按 WSL VMCreatorId 配置，不能假定只影响一个发行版 | 当前 NO-GO |

微软不支持在 Windows Home 安装 Hyper-V 角色。本机现有版本不能直接作为已验证
部署环境。升级或另选独立宿主均须具体审批；本轮部署位置待定。
资源仅为估算：Windows Worker VM 约 4–6 GiB 内存，若独立出口 VM 再预留
0.5–1 GiB；磁盘、Windows 许可、CPU 和升级维护窗口待选型测量，不是已验收容量。
Linux Worker 会将 TokenUser 契约改为 Linux 身份与隔离标识，不能在本路线下静默替换。

## 4. 身份与权限实施契约

1. 受保护启动器用 `LogonUserW(LOGON32_LOGON_BATCH)` 获得专用非管理员账户
   主令牌，验证 TokenUser，再派生受限令牌。也可另行规划 SCM 服务登录方式。
2. 用 `CreateProcessAsUserW` 和 `CREATE_SUSPENDED` 创建 Worker，明确可执行路径，
   最小环境及允许继承的句柄列表；所需权限仅授予启动器，不提升 FastAPI。
3. 启动器通过子进程句柄查询真实 TokenUser、创建时间、程序摘要及受限状态，
   核对批准 SID 与受保护环境，加入禁止 breakaway、kill-on-close 的 Job。
   全部成立后恢复执行；失败直接终止并等待，不能只关闭未纳管进程句柄。
4. 账户允许所选 Batch/Service 登录，拒绝交互与远程交互，不能笼统 Deny Logon。
   CreateProcessWithLogonW 要求本地交互登录，不符合该方案；仅更换网络凭据也不算换身份。
5. 账户密码由人工配置于系统受保护凭据存储，仅启动器可访问；不写环境、参数、
   job 或日志。具体存储机制及轮换方案在 plan 中确定。本轮未读取密码/API Key。
6. 程序、授权输入及审计收据只读，输出独立可写；检查父目录删除/替换权限。
   Worker 不读取原仓库、审批 DB、宿主用户目录及凭据存储。IPC 认证调用者并限制消息。
7. 超时、取消、启动器异常退出均回收完整进程树，等待退出后再清理任务资源。

## 5. 网络实施契约

- Worker VM 只连接 ADLL 专用隔离网络，不接宿主默认 NAT 或桥接网络，无额外网卡。
- 专用 Guest 所有 Profile 默认出站 Block，仅允许指定主体/程序到固定出口地址端口；
  检查并处理 Guest 镜像中的宽泛 Allow，不添加与允许路径重叠的全量显式 Block。
- 专用出口不转发任意 IP，不提供通用 CONNECT/SOCKS/URL 代理；只接受固定
  Messages POST。认证调用者与审计收据，校验字节摘要；上游固定域名、方法和路径，
  TLS 校验证书，禁重定向，不重编码已审核 JSON，不自动重试。
- 出口 OS 默认拒绝，只允许批准的上游地址集合及明确基础设施例外。
  可信解析器仅解析批准域名，地址更新原子化并失效旧证据；不把共享 IP 等同域名。
  Worker 不获得通用 DNS 通道。DNS、时间、证书状态检查等具体依赖须在 plan 中列明。
- IPv6 使用同等策略或在专用环境禁用并验证；验证回环、局域网、代理、UDP、
  子进程及系统服务代发均不能绕过出口。有限探测不能代替完整策略覆盖分析。
- 禁宿主目录/驱动器共享及剪贴板旁路；管理通道只交换有界任务，不提供通用命令或转发。
- 宿主默认出站策略不变；不复用、修改 Codex 管理的账户、规则、服务。
  出口是隔离基础设施，不分拆业务状态、审批权或数据库，不引入业务微服务。

上述为执行契约，不是已安装策略或现成部署脚本。出口软件、虚拟交换与控制通道
确定后须生成具体配置、对象清单及验证步骤，再申请系统操作授权。

## 6. 发送前与发送后证据

发送前必须同时成立：

- 实际 Worker TokenUser、PID+创建时间、环境启动标识、镜像/程序摘要、Job 归属匹配。
- 生效网络策略、Profile、路由、接口、IPv4/IPv6 和出口策略形成可复核覆盖证明。
- 同一身份/环境存在非授权目标拒绝观测，原始 OS 事件关联进程及命中规则。
  5157 的 PID/目标/Filter Runtime ID 应与启动器身份记录关联；超时、重置、DNS 失败不单独算证明。
- prepared 行已提交；可信宿主读取该行并产生绑定 attempt_id、authorization_id、
  receiver、request_digest、环境及策略版本的单次收据。最终发送位置对不可变字节复核，
  不允许同时篡改 body 与 job 中的摘要通过。Worker 不获得数据库访问权。
- 采集器身份、版本、时间、有效期、原始证据引用可复核；策略变化或进程重建使证据失效。
  生产代码拒绝手填布尔值和 synthetic 证据。放行前复核授权撤销与有效期。

发送后记录：真实传输回执、HTTP 状态、服务商请求标识（如有）、原始响应字节摘要、
解析文本摘要、同 attempt 的唯一审计终态、核验记录、隔离方案版本/策略摘要，
以及满足验收条件时产生的 ProposalVersion。传输成功与业务响应有效分别判断。

发送前拒绝为 not_sent；进入发送但证据不完整为 possibly_sent；充分响应证据支持
confirmed_sent。取消不能撤回已发数据。结果落库失败保留发送事实并阻断业务完成。
首次发送前不要求首次服务商响应或发送后摘要；出口健康和经授权的无业务载荷
连通性检查属于不同证据。本轮没有执行百炼连通性或真实请求。

## 7. 最小修改范围与验收要求

| 范围 | 必需修改 |
|---|---|
| win32 / sandbox | 独立账户主令牌、挂起创建、子进程身份、Job 失败回收、输入/输出权限分离 |
| WorkerAgentAdapter / factory | 对接真实执行环境，门禁前不给发送权限或凭据 |
| GenerationRequest / outbound | 已持久化审计收据与最终字节绑定 |
| network_boundary | 前置策略证明、来源验证、有效期及后置回执分离 |
| Worker / 出口 | 固定目的地、无任意转发、原始响应摘要与可信回执 |
| audit / verification | 证据引用、方案版本、唯一终态及失败恢复；不能缺证据标记完成 |

离线验收覆盖摘要篡改、收据重放/跨任务替换、身份不符、策略失效、采集失败、
超时/取消与终态唯一性。后续真实 OS 验收必须覆盖进程树回收、身份、目录拒绝、
v4/v6/回环/代理/服务代发拒绝、允许出口及策略变更失效。Mock 不能替代这些证明。
首次真实请求须另行批准，使用合成业务内容；生产网络验收未完成前始终 NO-GO。

## 8. CI 与离线验证记录

[GitHub run 39963768970](https://github.com/livepass/ADLL/actions/runs/39963768970)
对应上述基线。后续复查已确认 backend 与 frontend 均 completed/success，列出的
全部工作流步骤均 success，没有 skipped 步骤。

- backend 日志最终汇总：`282 passed, 3 skipped, 1 warning in 939.11s (0:15:39)`，
  时间为 2026-10-23 14:01:35 UTC（北京时间 22:01:35）。
- frontend：20 passed，构建成功。
- pytest 的 3 skipped 与工作流步骤跳过是不同层级。当前汇总未列逐项原因；
  仓库虽有 staging 条件跳过代码，不能仅凭源码将实际 3 项逐一归因。
- 前轮本地只做 58 个应用 Python 文件 AST 解析，以及合成字节摘要匹配/篡改/缺失、
  缺主体/缺规则拒绝的纯函数检查；未启动 Worker 或运行会改 ACL 的全量测试。

CI 成功不等于真实身份或网络隔离通过。此前报告中的 CI pending 已由本次复查更新。

## 9. 部署授权与回滚

待人工确定部署宿主及资源后，分别批准：VM/网络/出口创建、账户与登录权、
启动器安装、专用 ACL、专用环境策略及审计配置、凭据注入、真实 OS 验收。
真实百炼调用单独授权。当前不得执行这些操作。

回滚：先关闭发送入口，终止并等待 Worker 树退出，断开专用网络，保存审计证据，
再按部署清单中的精确对象 ID 撤销自建资源。不能先删除策略后留下进程运行；
不能使用宽泛通配符删除规则，也不撤销 Codex 或其他应用资源。

结论：路线已获人工同意，文档完成；部署位置待定，编码/系统操作未执行，
生产发送仍 NO-GO。

## 10. 官方依据（2026-10-23 核查）

- [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)
- [CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)
- [LogonUserW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonuserw)
- [CreateProcessWithLogonW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createprocesswithlogonw)
- [Firewall 规则优先级](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)
- [WFP 用户过滤](https://learn.microsoft.com/en-us/windows/win32/fwp/permitting-and-blocking-applications-and-users)
- [WFP 仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration)
- [Hyper-V 要求](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/Install-Hyper-V)
- [Hyper-V Firewall](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/hyper-v-firewall)
- [5157 拒绝事件](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-5157)

宪章自检：保持模块化单体与既定技术栈；真实权限与审批不降级；不创建第二状态权威；
事实、估算、待验证事项分开；重要技术细节待规划审批，不代替用户批准。
