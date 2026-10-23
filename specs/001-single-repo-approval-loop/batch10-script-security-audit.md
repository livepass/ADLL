# 批 10 遗留脚本最终静态安全审核

**Date**: 2026-10-21
**范围**：逐行静态审核
`backend/scripts/create_adll_probe_account.ps1`、
`backend/scripts/account_selfcheck.py`；仅做最小安全修正。
**未执行**账户创建、ACL 修改、真实模型调用或防火墙变更。
**审核后状态**：两项脚本语法解析通过（`PS_PARSE_OK`、`ruff --select E9,F63,F7,F82` 通过）；
账户仍 **NOT CREATED**；S9 仍 **NOT RUN**。

## 1. 逐项结论

| # | 审核项 | 结论 | 风险位置 | 最小修正 |
|---|---|---|---|---|
| 1 | 账户已存在时停止，不覆盖/修改/删除 | **PASS** | PowerShell L47-49：`Get-LocalUser` 检查在口令/创建之前，直接 `throw`；只有 `$created=true` 的 catch 分支才 `Remove-LocalUser` | 无（保留） |
| 2 | 只修改约定临时目录；不改项目/真实仓库/生产 DB/既有账户/防火墙 | **PASS（脚本行为）**；**生产隔离仍 FAIL** | PowerShell 只对 `ProgramData\ADLL-Account-SelfCheck` 下 `Base/Parent/Work` 执行 `Set-Acl`（L82-104）；Python `deny/restore` 均经 `_assert_within(run)`（L95-116）。脚本不调用防火墙/既有账户 API | 新增：Base 非空时拒绝（L53-58）；Base/Parent/Work reparse 检查；Python `--base` 限定为 `ADLL-Account-SelfCheck` 根、`--project-root` 限定在 ADLL 项目内（L264-275） |
| 3 | 口令始终本地安全交互，不记录明文/日志 | **PASS** | PowerShell L60 `Read-Host -AsSecureString`；仅存 `$secure`/`PSCredential`；`Start-Process -Credential`（L115-117）；无任何输出/文件写入口令 | 无 |
| 4 | 真正以 ADLLTest SID 执行，不继承管理员 | **PASS** | `New-LocalUser` 后检查不在 Administrators、在 Users（L70-79）；`Start-Process -Credential ("$env:COMPUTERNAME\$Name")`（L112-117）；父进程复核 `parsed.sid == $sid` 与 groups 不含 Administrators（L133-136） | 增加父进程 SID/组复核；`account_selfcheck` 记录 `whoami /user` SID |
| 5 | 路径遍历/符号链接/junction | **PASS（含 TOCTOU 残余）** | Python `_assert_within`/`_assert_not_reparse`（L53-67），`deny/restore` 解析真实路径并限于 `run`（L95-116）；PowerShell `Assert-NotReparse`（L15-22）；清理不递归删除非空 `Work`，避免 junction 穿越（L201-211） | 新增 base/out/project 约束；`--out` 不得在账户可写 base 内；删除前仅检查直接子项，非空则保留并报告 |
| 6 | ADLLTest 可篡改 evidence.json | **已修复** | 原实现把 `evidence.json` 写在 Base（账户 Modify）。修正后：`--out -` 由父进程重定向到 `Parent\selfcheck.stdout.json`（Parent 仅 SYSTEM/Administrators），最终 `Parent\evidence.json` 由父进程写入（L107-117、L167）；账户无法写 Parent | 增加 nonce（L107、L134）、父进程复核 SID/检查项、保存原始 stdout 的 SHA-256；**残余**：证据由账户进程自报，nonce/脚本/应用哈希不能证明其未伪造输出 |
| 7 | 异常退出清理/独立回滚，不隐瞒残留 | **PASS（含强制终止残余）** | Python `finally` 恢复 ACL、删除 `run`、记录 `cleanup_errors`（L395-409）；`job_check` 恢复 job ACL 失败即抛出；PowerShell 捕获并报告账户/Work/Profile 清理失败；探针启动后异常**不自动删除账户**，保留供调查（L214-226） | 增加 live-process 检查失败即不删除；非空 Work 不递归删除；`cleanup_errors` 使证据 `ok=false` |
| 8 | TEST-NET 失败不得作为 OS 出站 allowlist PASS | **PASS（已修正）** | Python 原先把 `network.loopback/external_testnet` 纳入 `ok`；现已从 `checks` 移除，`network_is_informational=true`（L285-291、L379-393）；父进程验证项不含 network | 网络结果仅作信息性记录；S9 仍需独立网络观测 |

## 2. 关键代码位置（审核后）

### create_adll_probe_account.ps1

- L47-49：账户存在即停止。
- L60-68：SecureString 口令；创建标准账户；`$created` 标记。
- L70-79：Administrators/Users 组检查。
- L82-104：仅 Base/Parent/Work ACL；Parent 管理员独占；Work 账户 Modify。
- L107-117：nonce、父进程重定向 stdout、`Start-Process -Credential`。
- L128-153：父进程复核（脚本/应用源码哈希、nonce、SID、组、退出码、self_check/
  generate/job/文件检查、cleanup_errors、project_read）。
- L167：`Parent\evidence.json` 由父进程写入（ADLLTest 不可写）。
- L175-198：live-process 检查、账户删除/保留；profile/Work 清理失败报告。
- L199-226：异常路径；仅探针未启动时自动删账户；探针启动后保留并报告。

### account_selfcheck.py

- L53-67：reparse/路径边界断言。
- L95-116：ACL 修改仅限 `run`。
- L188-237：Job Object 检查；ACL 恢复失败即报错。
- L258-280：`--base`/`--out`/`--project-root` 约束；nonce。
- L285-291：`cleanup_errors`、`network_is_informational`。
- L379-409：`ok` 不含网络；恢复/删除错误写入证据并使 `ok=false`。
- L411-414：`--out -` 输出到父进程重定向；否则拒绝 base 内路径。

## 3. 残余风险（未消除，必须随验收记录）

1. **账户可写项目根**：`D:\wo\code\ADLL\ADLL` 对 `Everyone` 为 FullControl；
   ADLLTest 运行期间仍可修改项目源码/潜在 DB。脚本只做脚本/`app/*.py` 前后哈希，
   不能阻止“修改后恢复”的瞬时篡改，也不能覆盖 venv。**生产 S10/S14 继续不通过**。
2. **证据自报**：`account_selfcheck` 在账户内运行，文件/网络结论由该账户输出；
   父进程可复核 nonce/SID/结构，但不能把输出当作独立第三方证明。最终生产验收
   需要 VM/容器或独立观测。
3. **TOCTOU**：Python/PowerShell 的“检查路径→Set-Acl/删除”之间存在竞态；
   `Work` 由账户可写，恶意账户可创建 junction。已避免递归删除非空 Work，并拒绝
   reparse 直接子项，但不能完全消除竞态。
4. **强制终止**：若 PowerShell 被强制结束，账户/Work/Parent 可能残留；需按下方
   手动清理。脚本无法在 SIGKILL 后执行 finally。
5. **网络**：TEST-NET/回环失败仅信息性；S9 仍 NOT RUN，未做真实外站观测。

## 4. 审核后供用户手动执行的准确命令

在**管理员 PowerShell**（或 Claude Code 的 `!` 交互，若该会话已提升）中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::SetEnvironmentVariable('PSModulePath','C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules','Process'); & 'C:\ProgramData\ADLL-Account-Staging\scripts\create_adll_probe_account.ps1'"
```

- 脚本会提示输入 `ADLLTest` 的临时口令（隐藏输入）；请勿把口令发到聊天。
- 证据：`C:\ProgramData\ADLL-Account-SelfCheck\parent\evidence.json`（ADLLTest 不可写）。
- 脚本结束会询问是否删除 `ADLLTest`；若探针启动后异常，账户被保留供调查，需按提示处理。
- 若未提升权限，`#Requires -RunAsAdministrator` 会拒绝；请先在管理员 PowerShell 中运行。

### 手动回滚/清理（仅在脚本异常残留时）

```powershell
# 1) 查看账户与进程
Get-LocalUser -Name ADLLTest -ErrorAction SilentlyContinue
Get-Process -IncludeUserName -ErrorAction SilentlyContinue | Where-Object UserName -like '*\ADLLTest'

# 2) 无进程后删除账户（仅本轮创建；不删除其他账户）
Remove-LocalUser -Name ADLLTest

# 3) 删除 profile（若存在且未加载）
$u = Get-LocalUser -Name ADLLTest -ErrorAction SilentlyContinue
# 账户已删除时按 SID 查找：
Get-CimInstance Win32_UserProfile | Where-Object LocalPath -like '*ADLLTest*' | ForEach-Object {
  if (-not $_.Loaded) { Remove-CimInstance -InputObject $_ }
}

# 4) 检查并删除临时目录（先确认无 reparse point；不要递归穿越 junction）
Get-ChildItem -LiteralPath 'C:\ProgramData\ADLL-Account-SelfCheck' -Force
# 确认目录为空/仅本轮合成数据后：
Remove-Item -LiteralPath 'C:\ProgramData\ADLL-Account-SelfCheck' -Recurse
```

> 若 `Remove-LocalUser`/ACL 恢复/目录清理失败，必须记录失败错误并保留现场，
> 不得掩盖；下一次验收前人工处理。

## 5. 结论

- 8 项静态审核均已给出结论；关键问题（证据写入账户可写目录、网络结果误入 PASS、
  路径/清理风险）已做最小修正。
- **未执行**账户创建/探针；因此账户实际 SID/文件拒绝/防火墙拒绝/self_check 一致性
  仍 **NOT RUN**，不得作为 PASS 写入验收矩阵。
- S9 仍 NOT RUN；生产 S10/S14 仍不通过（项目根 Everyone 可读，且尚未实际账户验证）。
