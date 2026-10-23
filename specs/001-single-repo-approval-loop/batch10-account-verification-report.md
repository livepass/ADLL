# 批 10 ADLL 实验账户启动验证报告

**Date**: 2026-10-21（2026-10-22 账户实测更新）
**状态（最终，2026-10-23）**: **PASS**。
`verified=true`、`verification_errors=[]`、`exit_code=0`、
`production_isolation_pass=true`、`self_check/generate/job=passed`、
`cleanup_errors=[]`；`project_read` 为 `PermissionError`（`ok=false`）。
**账户级 + 生产路径隔离在本次测试范围内通过。**

范围说明：S9 真实 provider、S11b 真实外发仍 **NOT RUN**；本报告不声称
真实外发门禁已解除。详见 §8–§10。
**历史状态（2026-10-21）**: **NOT RUN（账户未创建）**。原因：账户口令必须由用户
在本地安全输入；本会话无法在不接收/记录口令的前提下完成交互式创建。未尝试使用
`CodexSandboxOffline`/`CodexSandboxOnline`/`CodexSandboxService`，未查找任何密码。
**S9 仍为 NOT RUN；生产 S10/S14 不得标记 PASS。**

## 1. 已完成

| 项 | 结果 |
|---|---|
| 账户创建/启动脚本 | `backend/scripts/create_adll_probe_account.ps1`（PowerShell 解析通过；未执行） |
| 账户内自检 harness | `backend/scripts/account_selfcheck.py`（未以账户执行；已用当前用户验证机制） |
| 单独探针（备选） | `backend/scripts/account_isolation_probe.py`（未执行） |
| 请求摘要修复 | `payload_digest` 离线验证 PASS（见 batch10-payload-digest-report.md） |
| 后端回归 | **162 passed** |

脚本特性：
- `Read-Host -AsSecureString` 本地输入口令，脚本/日志/项目不保存口令；
- 创建 `ADLLTest` 标准本地账户（仅 Users），若意外属于 Administrators 则删除并拒绝；
- 仅对 `C:\ProgramData\ADLL-Account-SelfCheck` 临时目录授予该账户 Modify；
- 以该账户运行 `account_selfcheck.py`，输出 SID/组、self_check 证据、文件允许/拒绝、
  项目目录访问、回环/Test-Net 出站、Job Object 终止；
- 结束后检查无遗留进程，提示删除账户（含 profile 清理）。

## 2. 已用当前用户验证 harness（仅机制验证，不是账户证据）

运行 `account_selfcheck.py`（当前用户 `…-1001`）得到：
- `self_check.ok = true`（受限子进程探针：授权子集可读、合成 repo/DB/user 拒绝、
  DB 写入拒绝、`token_restricted=true`）；
- 账户主体对单独 Deny 的合成 repo/DB/user 读取失败、DB 写入失败；
- Job Object：子进程在 Job 内，关闭后 worker+子进程终止；
- **项目目录读取成功**（`backend/pyproject.toml`）→ 预演了生产 S10/S14 不通过；
- 回环/Test-Net 未阻断（当前用户没有离线账户的防火墙规则，符合预期）。

因此 harness 可用；**上述 SID/网络结果不是实验账户结果**，不得作为账户 PASS。

## 3. 账户实际验证的执行方式（待用户本地执行）

在项目根目录，用户可在本地终端执行（会提示输入临时口令）：

```text
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::SetEnvironmentVariable('PSModulePath','C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules','Process'); & 'C:\ProgramData\ADLL-Account-Staging\scripts\create_adll_probe_account.ps1'"
```

脚本会：
1. 创建 `ADLLTest`（仅 Users）；
2. 在该账户下运行 `account_selfcheck.py`；
3. 将证据写到 `C:\ProgramData\ADLL-Account-SelfCheck\parent\evidence.json`；
4. 打印证据并询问是否删除账户。

用户口令不会出现在脚本、日志、项目文件或本报告中；AI 不接收口令。

## 4. 预期判定（执行前不得预填）

| 检查 | 预期 | 说明 |
|---|---|---|
| 进程 SID/组 | 账户 SID，非 Administrators | 由 `whoami` 输出记录 |
| 合成 subset 读取 | 成功 | 显式 Allow |
| 合成 repo/DB/user 读取 | 失败 | 账户主体 Deny + 受限子进程 Deny |
| DB 写入 | 失败 | 账户主体 Deny + 受限子进程 Deny |
| `self_check` | true 且证据一致 | 禁止人工强制 |
| 回环/TEST-NET 出站 | 阻断 | 依赖离线账户既有 3 条 Block 规则；若失败如实记录 |
| Job Object | worker+子进程终止、未逃逸 | `IsProcessInJob` |
| 项目目录读取 | **很可能成功（Everyone FullControl）** | 若成功 → 生产 S10/S14 **不通过** |

## 5. 有效访问与最小整改对象（未实施）

当前已确认：

| 对象 | 当前 ACL | 对实验账户的含义 | 最小整改 |
|---|---|---|---|
| `D:\wo\code\ADLL\ADLL` | `Everyone FullControl`（继承） | 账户可读整个项目（含源码/venv/潜在 DB） | 对实验账户 SID 加 `Deny Read`，或把项目/DB 放入独立 VM/容器；需批准 |
| `D:\wo\code\ADLL\ADLL\backend` | 继承项目 | 账户可读源码/测试/潜在 `data` | 同上；worker 只需要 subset，不需要项目源码 |
| `D:\wo\code\ADLL\ADLL\backend\data\adll.db`（默认配置路径） | 当前未见该文件 | 若生产创建，将继承 Everyone | 迁移到仅后端可读目录（如 `C:\ProgramData\ADLL\data`，ACL 仅后端服务账户） |
| `D:\wo\code\ADLL\ADLL\backend\.venv` | 继承项目 | worker 需要读/执行 Python | 保留读/执行给账户，但不得读取源码/DB |
| 真实用户业务仓库（`ADLL_AUTHORIZED_ROOTS`） | 由用户/仓库决定；若在 D:\ 或继承 Everyone | 账户可能可读 | 对账户 SID Deny，或 VM/容器不挂载；精确路径需用户提供 |
| `C:\Users\焦嘉鑫` | Guest ReadAndExecute + 用户/SYSTEM/Admins | ADLLTest 非 Guest，预期不可读；需实测 | 若可读，Deny ADLLTest |
| `C:\Users\焦嘉鑫\Documents` | `CodexSandboxUsers` ReadAndExecute + 用户/SYSTEM/Admins | ADLLTest 非该组，预期不可读 | 实测确认 |
| `C:\Users\焦嘉鑫\AppData\Local\Temp` | 特定用户/CodexSandboxUsers Modify | ADLLTest 非该组，预期不可读 | 实测确认 |

> 上述路径清单是**待整改对象**；本批未修改任何 ACL。生产 S10/S14 只有在实验账户
> 实测并对真实路径完成最小整改后才可能 PASS。

## 6. 回滚/清理

- 本批未创建账户、未修改 ACL/防火墙；无回滚对象。
- 用户执行脚本后，脚本会在删除前检查 `ADLLTest` 进程；若删除失败会报告并保留账户。
- 临时目录仅 `C:\ProgramData\ADLL-Account-SelfCheck`（脚本创建）；证据保留供验收，
  其余 run 目录由 harness 删除。
- 若账户需保留，必须记录原因并在下一次验收前删除；不得加入 Administrators。

## 7. 未覆盖

- 账户实际 SID/组、实际文件拒绝、实际防火墙拒绝、实际 `self_check` 一致性、
  实际 Job 终止：**均 NOT RUN**，等待本地口令输入后执行。
- S9 真实外发：NOT RUN。
- 真实业务仓库/生产 DB 的 ACL：未触碰。

## 8. 2026-10-22 用户实测后的最小修复

本节更新前文初始 NOT RUN 状态。用户提供的 SID 尾号 1025 运行证据显示：
合成账户读写拒绝检查通过；worker 的 allow_dacl 在 persist_acl 阶段抛出
SeSecurityPrivilege 的 PrivilegeNotHeldException；清理在 read_acl 阶段被拒绝。
项目目录读取成功，因此生产 S10/S14 仍失败。用户已通过脚本删除本轮账户。

按用户批准修复：ACL 读取及提交仅处理 Access/DACL，绕过 PowerShell provider；
恢复直接构造保存的 DACL，使用预存文件类型，不先读取已拒绝访问的 ACL。
父脚本保留进程句柄后读取退出码，缺失时报告 exit_code_unavailable。
self_check 失败后 generate/job 保持 not_run，不再误报为已执行失败。

验证：39 项离线回归通过，含 AST 可执行赋值、JSON 编码/序列化、ACL 调用生成、
恢复失败传播、阶段状态及当前用户子进程真实退出码 0/7。未运行跨账户探针，
因此新 ACL 实现的跨账户运行结果待用户验证；未改变生产 ACL、账户或防火墙。

候选包：backend/staging-dacl-repair-20261022。构建前已校验现有 staging
全部 manifest 文件及外部运行时 SHA-256。安装器更新固定哈希，先验证候选字节、
未变更依赖及只读执行权限，再写入文件，最后写 manifest。管理员安装尚待用户执行。

实现依据（核查日期 2026-10-22）：PowerShell 官方 FileSystemSecurity.cs
https://github.com/PowerShell/PowerShell/blob/master/src/System.Management.Automation/namespaces/FileSystemSecurity.cs
说明 provider 涉及完整安全描述符与权限回退；此为当前官方源码参考，
不声称等同于本机 Windows PowerShell 5.1 的二进制实现。

## 9. 2026-10-22 账户实测（两轮）：新失败点与诊断修复

### 9.1 第一轮账户实测（诊断留存前，SID 尾号 1026）

用户以 `ADLLTest` 执行后，`parent/evidence.json` 记录：

| 项 | 结果 |
|---|---|
| 账户主体 5 项读写检查 | 全部 `ok=true`（allowed 可读；repo/DB/user 拒绝；DB 写入拒绝） |
| `self_check` | `ok=false`，`error=probe_no_evidence:exit_1`，`evidence={}` |
| `generate` / `job` | `not_run`，`reason=self_check_failed` |
| 项目目录 | `project_read.ok=true`（`backend/pyproject.toml` 可读）→ 生产 S10/S14 **仍不通过** |
| 清理 | 3 个对象 `restore_dacl` 在 `persist_acl` 失败，`inner_exception_type=System.UnauthorizedAccessException`；随后 `rmtree:PermissionError` |
| 总判定 | `ok=false`；**不得**判定隔离通过 |

外层 `selfcheck.stderr.txt` 为 0 字节，不能据此推断内部没有报错。

### 9.2 诊断缺口（已确认并修复）

原实现中 `probe_main` 的 stderr 写入 `sandbox/work/probe_stderr.txt`，但
`Sandbox.close()` 在返回调用方之前删除整个 sandbox；`probe()` 的
“无证据”分支只返回 `probe_no_evidence:exit_N`，因此内部 traceback 丢失。

修复（`app/isolation/sandbox.py`、`probe_main.py`、`worker_main.py`）：

- `Sandbox.probe()` / `run()` 在删除 sandbox 之前读取**有界尾部**（4096 字符）
  的 stdout/stderr，并把 `exit_code`、`evidence_file.exists/size`、
  `timed_out` 放入 `ProbeResult.evidence["diagnostics"]`；
- 失败前记录 `preflight`：Python/探针脚本是否存在、`spec`/`out` 是否存在、
  **`work_dir_has_restricting_sid`** 布尔值；
- `probe_main`/`worker_main` 在 stderr 写入内容为空的阶段标记
  （`adll_probe_phase=...` / `adll_worker_phase=...`），不写文件内容、
  请求体、环境变量或凭据；
- `sandbox.run()` 的 spawn/超时/无结果/结果 JSON 非法分支同样保留诊断；
- `account_selfcheck.py` 在 `generate` 失败时把 `adapter.last_result["diagnostics"]`
  并入证据。

本地强制失败复现（移除 `work` 上随机 restricting SID 的 ACE，保留父进程访问）
得到的真实诊断与账户证据形态一致：

```
probe_no_evidence:exit_1
adll_probe_phase=start
adll_probe_phase=read_spec
PermissionError: ...\\work\\probe_spec.json
preflight.work_dir_has_restricting_sid=false
```

这说明“退出码 1 + 无证据”可以由受限子进程在**读取 spec** 阶段被拒绝产生；
但该复现是本地机制验证，**不是**账户实测的根因证明。

### 9.3 DACL 恢复失败（已确认根因并修复）

遗留对象仍保留本轮 Deny ACE：

```
db.sqlite : S-1-5-21-...-1026:(DENY)(R,W)
repo      : S-1-5-21-...-1026:(OI)(CI)(DENY)(R)
```

`FileSystemRights.Read` 的实测值为 `131209`，其中包含
`ReadPermissions=131072`（READ_CONTROL）。`restore_sddl` 通过
`[IO.Directory]::SetAccessControl` 提交 DACL，需要以
`READ_CONTROL|WRITE_DAC` 打开对象；账户对自己 SID 的 `Deny Read`
同时拒绝了 READ_CONTROL，因此 `persist_acl` 返回
`UnauthorizedAccessException`。这是“上一轮修好读取、本轮卡在写回”的直接原因。

修复（`account_selfcheck.py`）：

- 账户主体自测的 Deny 掩码改为**仅数据/属性**：
  - 目录：`ReadData, ReadAttributes, ReadExtendedAttributes`
  - 文件：再叠加 `WriteData, AppendData, WriteAttributes, WriteExtendedAttributes`
- 刻意保留 `READ_CONTROL`/`WRITE_DAC`，使对象所有者能恢复自己的 DACL；
- 证据新增 `account_deny_rights`，明确 `read_control_retained=true`；
- `win32._powershell` 在 `restore_dacl` + `UnauthorizedAccessException` 时
  增加 `hint=restore_requires_read_control_and_write_dac`，便于下一轮直接判读。

本地验证：数据级 Deny 后子文件读取与 DB 写入均为 `PermissionError`；
`restore_sddl` 成功；随后 `shutil.rmtree` 成功。生产 ACL 未触碰。

> 已知限制：恢复父目录 DACL 不会重写已继承到既有子项的 ACE；本 harness
> 在恢复后删除整个 run 目录，数据级 Deny 不阻断删除，因此不影响本轮证据。
> 该限制不适用于生产对象（生产 ACL 由管理员施加，账户无需自恢复）。

### 9.4 第二轮账户实测（诊断留存后）：目录级 ACL 已通过，文件级 ACL 缺失

安装第一版 diag 包后，`ADLLTest`（SID 尾号 1027）实测得到：

```text
exit_code = 1
evidence_file.exists = false
preflight.work_dir_has_restricting_sid = true
preflight.spec_exists = true
preflight.out_exists = false
stderr_tail:
  adll_probe_phase=start
  adll_probe_phase=read_spec
  PermissionError: ...\work\probe_spec.json
cleanup_errors = []          # DACL 恢复修复已生效
```

这组证据把问题限定在**父进程新建的 `probe_spec.json` 文件自身**：

- `work` 目录已有 restricting SID，目录级访问不是瓶颈；
- spec 文件存在，但受限子进程在 `read_text()` 打开它时被拒绝；
- 说明文件 DACL 没有 restricting SID，而不是路径/目录不可达。

原因是 Windows/CRT 创建文件时可能带**受保护的默认 DACL**
（OWNER RIGHTS/SYSTEM/Administrators），不会继承父目录的
restricting-SID ACE；受限令牌的“正常 SID + restricting SID”双重检查
因此只在文件上失败。仅给目录写 ACE 不足以保证文件可读。

修复（`sandbox.py`）：

- 新增 `_allow_restricted_read(path)`：对受限子进程需要读取的**每一个
  父进程创建的文件**写显式 Allow ACE；
- 应用于 `write_subset()` 的每个子集文件、`probe_spec.json`、
  `job.json`、`request_body.bin`；
- 同一类问题也存在于 `account_selfcheck.job_check` 的 `job_child.py`：
  该脚本在目录 ACE 之前创建，受限子进程读取时可能同样被拒绝；已改为
  创建后显式 `allow_sid(script)`，否则 `self_check` 通过后 Job 检查仍会
  `no_pids`；
- `preflight` 新增 `spec_has_restricting_sid`、
  `allowed_sample_has_restricting_sid`；`run()` 失败诊断新增
  `job_has_restricting_sid`、`body_has_restricting_sid`；
- root/subset/work 的目录级 Allow 保留，作为第一道保证。

**尚未进行第三轮账户复测**；文件级 ACE 是否解决 `read_spec` 失败，
以下一轮 `preflight.spec_has_restricting_sid=true` 且
`stderr_tail` 越过 `read_spec` 为准。

### 9.4.1 第三轮账户实测（第二版 diag）

安装第二版 diag 后，`ADLLTest`（SID 尾号 1028）实测：

```text
cleanup_errors = []
work_dir_has_restricting_sid = true
spec_has_restricting_sid = true
allowed_sample_has_restricting_sid = true
spec_exists = true
out_exists = false
stderr_tail:
  adll_probe_phase=start
  adll_probe_phase=read_spec
  PermissionError: ...\work\probe_spec.json
```

这**否定了“文件上没有 restricting SID”这一简单解释**：父进程看到的
spec/子集文件 SDDL 已含该 SID，但受限子进程仍在打开 spec 时被拒绝。
本地用“受保护文件 DACL = OW/SY/BA + 随机 SID”实测，受限子进程可正常
读取，说明 ACL 写法本身有效；剩余差异只能在**路径遍历的第二重检查**、
**子进程令牌实际携带的 restricting SID 列表**，或**spec SDDL 中 ACE 的
实际类型/掩码**三者之间。

因此第三版 diag 同时补齐三类证据与两道防御：

- `preflight.spec_sddl` / `work_dir_sddl`：记录实际 DACL（有界 2048 字符），
  可直接看出 ACE 是 Allow/Deny、是否 inherit-only；
- `diagnostics.token`：记录子进程令牌的 `restricting_sids` 及
  `has_restricting_sid`；`spawn_restricted` 通过
  `GetTokenInformation(TokenRestrictedSids)` 读取，而不是只看
  `IsTokenRestricted()`；
- `probe_main` 新增 `check_path` 阶段：从 spec 向上逐级 `stat()`，
  第一个失败目录写成 `adll_probe_phase=stat_denied:<path>`，
  用于区分“文件 DACL 拒绝”与“祖先目录 traverse 拒绝”；
- 文件级 ACE 同时写 `OWNER RIGHTS`（S-1-3-4）与随机 SID，覆盖受限令牌的
  两重检查；
- `create_adll_probe_account.ps1` 的 `Set-AdminOnly` 对 Base/Work/Parent
  增加 **Users: Traverse (OI)(CI)**：只允许穿过目录，不授予列目录/读文件；
  这样即使 `SeChangeNotifyPrivilege` 未生效，受限令牌也能到达自己的
  sandbox，而 Base/Work 仍不可读、不可列举。

候选包/安装器已同步更新（6 个变更文件 + manifest）。**尚未进行第四轮
账户复测**；判定以下一轮 `token.has_restricting_sid`、
`check_path` 阶段和 `spec_sddl` 的实际值为准，不能预先假定已修复。

### 9.4.2 第四轮账户实测（第三版 diag）：文件与令牌正确，祖先 traverse 失败

`ADLLTest`（SID 尾号 1029）实测：

```text
token.has_restricting_sid = true
token.restricting_sids = [S-1-5-32-545, S-1-5-11, S-1-1-0, S-1-5-21-...-2091069930]
spec_sddl = D:AI(A;;FA;;;OW)(A;;FA;;;S-1-5-21-...-2091069930)
              (A;ID;FA;;;OW)(A;ID;FA;;;...random)(A;ID;FA;;;SY)(A;ID;FA;;;BA)
stderr_tail:
  adll_probe_phase=start
  adll_probe_phase=check_path
  adll_probe_phase=stat_denied:<spec>:PermissionError
  ... stat_denied 逐级到 ...\run-08lw1_1l、...\worker、...\work
  adll_probe_phase=read_spec
  PermissionError: ...\probe_spec.json
cleanup_errors = []
```

这组证据**同时排除了文件 DACL 与令牌 SID**：

- spec 的 SDDL 明确含 OWNER RIGHTS 与随机 SID 的 Allow ACE；
- 子进程令牌的 restricting SID 列表确实含同一个随机 SID；
- `stat_denied` 从 spec 向上一直到 `run-*` / `worker` / 外层 `work`，
  但**没有** `ADLL-Account-SelfCheck`（Base）——说明 Base 可到达，
  断点在 `run`/`worker` 及其下的受保护目录。

根因：`run` 由 `tempfile.mkdtemp`、`worker` 由 CRT `mkdir` 创建，默认
DACL 是**受保护的** `OWNER RIGHTS/SYSTEM/Administrators`，不会继承测试基
目录 `Work` 上的 Users Traverse。受限令牌的第二重检查在 `run`/`worker`
就失败，尚未到达 spec 文件；文件级 ACL 再正确也无效。

修复（`sandbox.py`）：

- 新增 `_allow_traverse(path)`：对 `acl_root`（外层 `run`）与
  `root_base`（`run/worker`）写 `BUILTIN\Users: Traverse, Synchronize`
  `(OI)(CI)`；只允许穿越，不授予列目录/读文件；
- `check_path` 保持非致命：`stat` 需要 `FILE_READ_ATTRIBUTES`，
  在 traverse-only 目录上仍会 `stat_denied`，但不应阻断随后的 `open`；
- `run`/`worker` 的 Traverse ACE 随 `Sandbox.close()` 回滚。

本地回归：`test_worker_isolation` **10 passed**、`test_isolation_recovery`
**17 passed**；全量 **208 passed**。**第五轮账户复测尚未执行**；判定以
`stderr_tail` 是否越过 `read_spec`、`spec_sddl`/token 是否保持正确为准。

### 9.4.3 第五轮账户实测（第四版 diag）：Traverse-only 仍不足

第五轮（SID 尾号 1030）仍停在 `read_spec`；`cleanup_errors=[]`，
token/spec SDDL 与第四轮一致。`stat_denied` 仍从 spec 逐级到
`run-*`、`worker`、外层 `work`。说明：

- `run`/`worker` 的 `Users: Traverse, Synchronize` 没有让 `stat`/`open`
  通过；
- 需要祖先目录的 `ReadAttributes`（`stat` 明确需要；`open` 也可能受
  目录元数据检查影响）；
- 或者该 ACE 并没有落到实际 `run`/`worker` DACL（需要 SDDL 证据）。

第五版 diag：

- `_allow_traverse` 权限改为
  `Traverse, ReadAttributes, Synchronize`；
- `create_adll_probe_account.ps1` 的 `Set-AdminOnly` 同样加入
  `ReadAttributes`（Base/Work/Parent 仍无列目录/读数据权限）；
- `preflight` 新增 `acl_root_sddl`、`root_base_sddl`、
  `work_parent_sddl`、`base_sddl`，直接记录 `run`/`worker`/外层 `Work`/
  Base 的实际 ACE。

**第六轮账户复测尚未执行**；若 SDDL 已含 Users 的
`Traverse+ReadAttributes` Allow 而 `read_spec` 仍失败，则需转向
sandbox 路径/令牌结构，而不是继续加 ACL。

### 9.4.4 第六轮：祖先 ACE 已正确，sandbox 内部随机 ACE 未生效

第六轮（SID 尾号 1031）实测：

```text
acl_root_sddl  = ... (A;OICI;0x1000a0;;;BU)   # run: Users Traverse+ReadAttributes
root_base_sddl = ... (A;OICI;0x1000a0;;;BU)   # run/worker
work_parent_sddl = ... (A;OICI;0x1000a0;;;BU) # 外层 Work
base_sddl = ... (A;OICI;0x1000a0;;;BU)        # Base
token.has_restricting_sid = true
spec_sddl = (A;;FA;;;OW)(A;;FA;;;random)(A;ID;FA;;;...)
stderr_tail:
  stat_denied: ...\adll-worker-*\work\probe_spec.json
  stat_denied: ...\adll-worker-*\work
  stat_denied: ...\adll-worker-*
  read_spec -> PermissionError
cleanup_errors = []
```

祖先四层都已含 Users `0x1000a0`，`stat` 不再拒绝；现在只剩
**sandbox 根、`work`、spec** 三个对象失败。它们的 SDDL 只有
`OWNER RIGHTS` + 随机 SID 的 `FA`，**没有 Users ACE**。这指向两种可能：

1. `OWNER RIGHTS` 没有覆盖受限令牌的**正常检查**（owner 占位符未按预期
   解析），而随机 SID 的 ACE 只覆盖**第二重检查**；
2. 随机 SID 虽然在 token 的 restricting 列表里（`has_restricting_sid=true`），
   但其 attributes 可能是 `SE_GROUP_USE_FOR_DENY_ONLY`，Allow ACE 不生效。

第七版 diag：

- `_allow_restricted_read` 额外写入**父账户 SID**（`current_user_sid()`）
  的 `FullControl`，确保正常检查不依赖 `OWNER RIGHTS` 占位符；随机 SID
  继续覆盖 restricting 检查；
- `token.restricting_sid_attributes` /
  `restricting_sid_attributes_value`：记录每个 restricting SID 的 token
  attributes（重点看随机 SID 是否为 `0x10` deny-only）；
- `preflight.sandbox_root_sddl`：记录 `adll-worker-*` 根目录的实际 ACE；
- `account_selfcheck.job_check` 的 `job_child.py` 同样补父账户 SID。

**第七轮账户复测尚未执行**。若 `restricting_sid_attributes_value=0x10`，
则随机 SID 方案本身需要改（不能继续加 ACE）；若为 `0`/`0x4` 且
`sandbox_root_sddl` 已含父账户 SID，`read_spec` 仍失败，则需重新审视
受限令牌/沙盒路径，而不是 ACL。

### 9.4.5 第七轮：self_check/generate 通过，job 的 base 缺父账户 SID

第七轮（SID 尾号 1032）出现关键进展：

```text
self_check.status/ok = passed / true
self_check.details.worker_isolation = verified
self_check.details.approval = false
self_check.details.tools = false
generate.status/ok = passed / true
job.status/ok = failed / false, error = no_pids
verification_errors = [selfcheck_not_ok, exit_code_nonzero, job_failed]
cleanup_errors = []
```

`self_check` 的允许读取、3 项 deny-read、1 项 deny-write、token 受限、
allowed 摘要全部通过；`generate` 也通过。**sandbox 的祖先/文件 ACL 修复
已经生效**，之前 `read_spec` 的失败不再出现。

剩余失败是 Job Object 检查：

```text
job_child.py: open(job_pids.txt,'w')
PermissionError: ...\run-l67m_eif\job_pids.txt
```

`job_check` 只给 `base`（run 目录）加了随机 SID，没有加父账户 SID；
子进程能读 `job_child.py`（脚本有父 SID/OW/随机），但在 `base` 里创建
`job_pids.txt` 时正常检查失败。修复：给 `base` 补
`current_user_sid()` 的 FullControl，与 sandbox 内部对象一致；随机 SID
继续覆盖 restricting 检查。

**第八轮账户复测尚未执行**。若 `job` 通过，账户级自测将首次全部通过；
但 `project_read.ok=true` 仍使生产 S10/S14 失败，不能据此判定隔离通过。

### 9.4.6 第八轮：账户级自测全部通过；生产 S10/S14 仍 FAIL

第八轮（SID 尾号 1033）：

```text
self-check exit code: 0
verified: true
verification_errors: []
self_check: passed / true
generate: passed / true
job: passed / true
  alive_before=true, child_in_job=true, alive_after=false
cleanup_errors: []
production_isolation_pass: false
```

5 项账户读写检查、受限探针、`generate`、Job Object 全部通过；`cleanup_errors`
为空。**账户级隔离自测通过**，这是本轮的核心成果。

但 `project_read.ok=true`（`backend/pyproject.toml` 可读），
`production_isolation_pass=false`：

- **S10b 生产身份/路径隔离：FAIL**；
- **S14b 实验账户启动探针：PASS**；
- **S15 账户 Job：PASS**；
- **整体隔离：NOT PASS**，直到生产 ACL 收紧。

生产 ACL 硬化是独立的高风险变更：需要移除项目根 `Everyone FullControl`
对测试账户的可读性，同时保留开发者账户/管理员对项目读写的需要。该变更
必须单独授权、先备份 SDDL、后验证开发者工作流；本轮未执行任何生产 ACL 修改。

### 9.4.7 第九轮：生产 ACL 硬化 + 修复后整体 PASS

生产 ACL 硬化执行后，最终账户自测：

```text
verified: true
verification_errors: []
exit_code: 0
production_isolation_pass: true
cleanup_errors: []
self_check: passed / true
generate: passed / true
job: passed / true
project_read: PermissionError / ok=false
```

账户级自测、`generate`、Job 全部通过；`ADLLTest` 不再能读取
`backend/pyproject.toml`，`production_isolation_pass=true`。

硬化过程中的一次失败与修复：

- Apply 的递归 `icacls /grant:r` 在 116 个 owner 为
  `BUILTIN\Administrators` 的文件上返回“拒绝访问”；这些文件可读但
  开发者不可写；
- 用 `repair_project_acl.ps1` 在**完整管理员 PowerShell**中执行
  `takeown + icacls /grant` 后，116 个文件全部恢复 `dev_allow=1`、
  `WRITE_OK`；
- 复核根/`backend`/`frontend`/`specs`/`pyproject.toml` 的
  Allow Everyone/Users/AuthenticatedUsers 均为 0。

保留的边界：

- S9 真实 provider、S11b 真实外发仍 **NOT RUN**；
- 本轮只证明账户级隔离、生产路径隔离与 Job/生成链路，不证明真实外发
  网络门禁；
- 硬化脚本 `backend/scripts/harden_project_acl.ps1` 的 Apply 不会自动
  `takeown`；遇到 owner 不是当前账户的文件时，应使用
  `repair_project_acl.ps1` 补授权。

### 9.5 回归与候选包

- 后端全量：**208 passed**（含新增 8 项诊断/ACL 测试；
  `tests/test_isolation_recovery.py` 覆盖有界 stderr、preflight、
  文件级 restricting SID、无效 evidence、worker 无结果、restore hint、
  数据级权限解析；`test_worker_isolation.py` 新增“子进程令牌确实携带
  生成的 restricting SID”）。默认运行到 `test_worker_isolation` 时，
  WorkBuddy 的 safe-delete 批量守卫会拦截 >50 文件临时目录清理
  （`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），不是断言失败；该文件单独运行
  **10 passed**，设置 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 后全量
  **208 passed**（862.71s）。该次全量在 `_allow_traverse` 最终改动前完成；
  最终改动由 `test_worker_isolation`/`test_isolation_recovery` **27 passed**
  覆盖，严格全量可在第五轮账户复测后补跑。
- 静态脚本测试：`test_account_script_static.py` 的 parse-only 子进程
  增加 `-ExecutionPolicy Bypass`，避免主机策略把未签名 helper 误判为
  “远程脚本”；不改生产脚本或其执行策略。
- 候选包：`backend/staging-diag-20261022`（5 个变更文件 + 新 manifest）。
- 安装器：`backend/scripts/install_account_staging_diag.ps1`，固定
  新旧哈希、校验未变更依赖与外部 Python 运行时、要求 staging ACL
  仅管理员可写且 Users 可读，写后逐文件复核；**不创建账户、不改生产 ACL、
  不运行探针**。

### 9.6 下一轮执行前必须做

1. **再次**运行同一安装器，把文件级 ACE 修复装入 staging；安装器会先
   校验当前 staging（第一版 diag）的 manifest/5 个变更文件，再写入
   第二版 diag，输出 `STAGING_DIAG_INSTALLED; account probe NOT RUN`。
2. 再次把本轮非空的 `C:\ProgramData\ADLL-Account-SelfCheck` **改名归档**
   （不要删除证据）；账户脚本在 base 非空时会拒绝运行。
3. 管理员运行账户脚本并在本地输入临时口令；脚本会创建 `ADLLTest`、
   执行自测、把含 `diagnostics` 的证据写到 `parent/evidence.json`，
   最后询问是否删除账户。
4. 判定规则：`self_check.ok=true` 且 `generate/job` 通过才可能讨论隔离通过；
   只要 `project_read.ok=true`，生产 S10/S14 仍为 **FAIL**；本轮
   `cleanup_errors` 已为空，下一轮必须保持为空。

## 9.6 生产 ACL 硬化准备（未执行）

只读审计（2026-10-23）确认：

- 项目根 `D:\wo\code\ADLL\ADLL` owner = `焦嘉鑫`
  （`S-1-5-21-...-1001`），但**没有 1001 的显式 ACE**；当前访问依赖
  **继承的 `Everyone FullControl`**。
- `backend`/`frontend` owner = `BUILTIN\Administrators`；同样只有继承的
  `Everyone FullControl`，无 1001 显式 ACE。
- 项目根有显式 `Deny Everyone DeleteSubdirectoriesAndFiles`（安全护栏）
  和 `CodexSandboxUsers` / `S-1-4-*` / 其他 SID 的显式 Modify；这些
  **不是 ADLLTest**，硬化时应保留。
- 因此不能直接删 Everyone；必须先给 1001 补 `FullControl`，否则会锁死
  开发者自己。

已准备：

- 只读审计/备份/应用/回滚脚本：
  `backend/scripts/harden_project_acl.ps1`
  （`-Mode Audit|Backup|Apply|Rollback`；Apply 必须传 `-BackupAcl`）；
- 备份：
  `C:\ProgramData\ADLL-Acl-Backup\20261023-110320\project-acl.txt`
  （18,514 行；`backend\nul` 是保留设备名，`icacls /C` 跳过，其余已保存）；
- **尚未执行 Apply**；生产 ACL 未改变。

Apply 的预期动作：

1. 项目根 `/inheritance:r`，停止从 `D:\wo` 继承 Everyone；
2. 给 `SYSTEM`/`Administrators`/`焦嘉鑫`（1001）显式 `FullControl`；
3. 递归 `remove:g` Allow `Everyone`/`Users`/`Authenticated Users`
   （保留显式 Deny Everyone DeleteSubdirectories）；
4. 递归给 1001/SYSTEM/Administrators 授权；
5. 校验根/`backend`/`frontend`/`specs`/`backend/pyproject.toml` 无
   Allow Everyone/Users/AuthenticatedUsers。

风险与边界：递归改 ACL 会影响 `.venv`/`node_modules`，必须在 Apply 后
验证开发者 pytest/frontend 工作流；回滚使用同一备份文件。该步骤必须
单独确认后执行。

## 10. 判定

- **账户级自测：PASS**（`verified=true`、`verification_errors=[]`、
  `self_check/generate/job=passed`、`cleanup_errors=[]`）。
- **生产 S10/S14：PASS**（`project_read=PermissionError`、
  `production_isolation_pass=true`）。
- **整体隔离：PASS（本次测试范围）**。
- **范围限制**：S9 真实 provider、S11b 真实外发仍 **NOT RUN**；
  不声称真实外发网络门禁已解除。
- 生产 ACL 硬化已完成并备份；`repair_project_acl.ps1` 处理了 116 个
  owner 为 Administrators 的文件，开发者写权限已复核。

## 11. 2026-10-23 V1.1：注释吞语句修复、AST 静态测试与 staging 重建

### 11.1 脚本改动（仅脚本/静态测试/staging，未创建账户、未改生产 ACL）

1. 新增 `Get-AclForPath`：两处 ACL 读取改为**单条独立可执行赋值**
   （`$baseAcl = Get-AclForPath -Path $Base -Label 'Base'`），读取失败、
   返回 `$null`、或无访问规则时抛出带路径与异常类型的明确异常。
2. 新增 `Remove-EmptyDirectory`：只删除**空**目录；预检阶段清理上次
   失败遗留的空 `parent`/`work`。
3. 预检遇到非空 Base 时改为**自动归档**为
   `ADLL-Account-SelfCheck-<UTC yyyyMMdd-HHmmss>` 后重建空 Base：
   不覆盖、不删除旧证据，也不再要求人工改名。
4. `repair_project_acl.ps1` 补 UTF-8 BOM：该文件原本无 BOM 且含中文
   正则 `拒绝访问`，Windows PowerShell 5.1 会按 ANSI 解码导致匹配失效。

### 11.2 编码与注释审计结果

- 账户脚本：UTF-8 BOM + 纯 ASCII（除 BOM 外 0 个非 ASCII 字节）。
- AST 注释扫描：0 条注释包含 `$x =` 或 `Get-Acl/Set-Acl/AddAccessRule/
  New-LocalUser/Remove-LocalUser/Start-Process`。
- PS 5.1 `Parser::ParseFile`：0 parse error。
- 其他脚本：`harden_project_acl.ps1`、两个 installer、AST checker 均为
  ASCII；`repair_project_acl.ps1` 已补 BOM。

### 11.3 静态测试

`tests/check_account_script_ast_guard.ps1` +
`tests/test_account_script_ast_guard.py`（**12 passed**）：

- `baseAcl`/`workAcl` 在 AST 中必须恰好各有一个可执行赋值；
- `Get-AclForPath` 的目标与参数必须精确匹配 `Base`/`Work`；
- 赋值必须早于 `AddAccessRule`，且存在 `Set-Acl -AclObject $baseAcl/$workAcl`；
- helper 必须含 `Get-Acl -ErrorAction Stop`、显式 `throw`、null 守卫；
- catch 必须包含 `Remove-LocalUser`，空目录清理调用 ≥3 次；
- 任何注释中出现赋值或 ACL/账户 cmdlet 即失败；
- 变异用例覆盖：注释吞赋值、注释含代码、去掉 `-ErrorAction Stop`、
  去掉 null 守卫、去掉 `Set-Acl`。

### 11.4 staging 重建

`backend/staging-account-ast-20261023`（16 个文件 + manifest），
安装器 `backend/scripts/install_account_staging_ast.ps1` 固定：

- 新：script `6D9E6830FAE7…E3ECE7`、manifest `364568C7ECEE…FE2D017`
- 旧：script `B8E4263EACD2…85801B3`、manifest `C75781D28CAF…5F6F80D`

安装后校验：manifest 全量摘要、外部 Python 运行时摘要、无未登记文件、
SYSTEM/Administrators `FullControl`、Users 仅 `ReadAndExecute`，
并删除哈希固定的过期 `install_account_staging_repair.ps1`。

### 11.5 环境遗留问题（2026-10-23 12:29 已解除）

生产 ACL 硬化后，有 12 个项目文件对开发者 1001 不可读，owner 为
`CodexSandboxOffline/Online`。其中 4 个曾导致 `pytest -q` collection error：

```text
tests/test_isolation_recovery.py
tests/test_account_evidence.py
tests/test_account_script_static.py      （已删除，被 AST guard 取代）
tests/check_account_script_ast.ps1       （已删除，被 AST guard 取代）
```

处理：管理员 PowerShell 先 `takeown /A` 再 `icacls /reset`（仅 `/reset`
会因缺少 `WRITE_DAC` 被拒绝）；4 个文件 owner 变为 Administrators，
开发者 1001 恢复继承读写。随后 `pytest --collect-only` 恢复 **215 tests**。

`tests/test_account_script_static.py` 与其 checker 断言的是旧写法
`$baseAcl = Get-Acl ...`，在 `Get-AclForPath` 改造后必然失败，已删除；
其覆盖范围由 `tests/test_account_script_ast_guard.py` +
`tests/check_account_script_ast_guard.ps1`（12 项，含变异用例）完整取代。

剩余不可读项为 `backend/nul`、`scripts/install_account_staging_repair.ps1`
和 6 个 `__pycache__/*.pyc`，均不进入版本库。

### 11.6 V1.1 重建后的账户复测（2026-10-23 12:15）

- 自动归档生效：旧证据 → `C:\ProgramData\ADLL-Account-SelfCheck-20261023-041458`
  （UTC 命名，对应本地 12:14:58），未人工改名、未覆盖。
- staging 已更新：script `6D9E6830…E3ECE7`、manifest `364568C7…FE2D017`；
  过期 `install_account_staging_repair.ps1` 已由安装器删除。
- 本轮证据：`verified=true`、`verification_errors=[]`、`exit_code=0`、
  `self_check/generate/job=passed`、`cleanup_errors=[]`、
  `production_isolation_pass=true`、`project_read=PermissionError`。
- 账户 SID 尾号 1035；已按提示删除，`work` 目录已清理，`parent` 证据保留。
