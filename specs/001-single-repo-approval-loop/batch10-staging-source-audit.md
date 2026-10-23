# 批 10 执行来源安全修正与管理员专用 staging

**Date**: 2026-10-21
**范围**: 只读 ACL 核查 + 建立管理员专用 staging；未创建账户、未修改真实项目 ACL、
未修改防火墙、未调用真实模型、未读取 Key、未 Commit/Push。
**结论**: 项目目录对 `Everyone FullControl`，因此**不能**让管理员从项目目录执行脚本。
已建立 `C:\ProgramData\ADLL-Account-Staging`（管理员写、Users 只读执行），
管理员执行链不再从项目加载脚本/Python 模块/DLL。

## 1. ACL 实测（只读）

| 对象 | 有效 ACL（关键） | 低权限 ADLLTest 能否修改 |
|---|---|---|
| `D:\wo\code\ADLL\ADLL` | `Everyone FullControl`（Allow）+ 一个 `DeleteSubdirectoriesAndFiles` Deny | **能**（Everyone 全控制；Deny 仅限删除子项，不能阻止写/改文件） |
| `...\backend\scripts` | 同上（继承） | **能** |
| `...\backend\.venv\Scripts\python.exe` | `Everyone FullControl` | **能** |
| `...\backend\.venv\Lib\site-packages` | `Everyone FullControl` | **能** |
| `D:\wo\python\Python312\python.exe` | SYSTEM/Administrators FullControl；Everyone ReadAndExecute | **不能**（只读执行） |
| `D:\wo\python\Python312\Lib` / `DLLs` | 仅 SYSTEM/Administrators 可写；Users 只读 | **不能** |
| `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` | SYSTEM/Admins TrustedInstaller；Users ReadAndExecute | **不能** |
| `C:\Windows\System32\cmd.exe` | 同上 | **不能** |
| `C:\Windows\System32\WindowsPowerShell\v1.0\Modules` | 仅 SYSTEM/Admins/TrustedInstaller 可写 | **不能** |
| `C:\Program Files\WindowsPowerShell\Modules` | 仅 SYSTEM/Admins/TrustedInstaller 可写 | **不能** |
| `C:\ProgramData\ADLL-Account-Staging` | SYSTEM/Administrators FullControl；Users ReadAndExecute | **不能**（只读执行） |
| `...\ADLL-Account-Staging\manifest.json` | 继承同上 | **不能** |

`PSModulePath` 原值包含 `D:\WindowsPowerShell\Modules`（非系统路径）；staging 脚本与
执行命令均将其替换为：
`C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules`。

## 2. 管理员 staging 内容

位置：`C:\ProgramData\ADLL-Account-Staging`（管理员写，Users 只读/执行）

```text
manifest.json
scripts\create_adll_probe_account.ps1
scripts\account_selfcheck.py
app\__init__.py
app\agents\{__init__,base,dashscope,worker}.py
app\core\{__init__,payload}.py
app\isolation\{__init__,sandbox,win32,probe_main,worker_main}.py
app\models\{__init__（空）,enums}.py
```

- `app/models/__init__.py` 在 staging 中为**空**，避免加载项目中的 SQLAlchemy 模型；
  `account_selfcheck` 只依赖标准库。
- Python 使用 **base** `D:\wo\python\Python312\python.exe`（只读），不使用项目 venv；
  启动参数 `-I -S`（无 site-packages、无 PYTHONPATH/user site）。
- 管理员脚本从 staging 读取自身、`account_selfcheck.py`、`app`；`--project-root`
  仅用于**只读**读取 `backend/pyproject.toml`（检测 ADLLTest 是否能读项目）。
- 管理员启动 Python 前清理 `PYTHONPATH`/`PYTHONHOME`，并将 `PATH` 限定为
  `C:\Windows\System32;C:\Windows`；工作目录为 staging（Users 只读）。
- 证据 stdout 由父进程重定向到 `C:\ProgramData\ADLL-Account-SelfCheck\parent`
  （管理员独占），最终 `parent\evidence.json` 由父进程写。

## 3. 固定摘要（人工复核）

**管理员脚本**：

```text
406C989269ED62BC1BFFD609A52FAA803ABCD04FD48337EA04CFEB9968100A0D
```

**account_selfcheck.py**：

```text
F17D84FDD749C9ACA1A3A7C5B2DB8D717C82674C770A9A7AE9ACDB3AFC620EF7
```

**manifest.json**：

```text
3E6CA8D3F89B869248EBF4D3A76ACE75E4854E8BE33627A8CEA2D3C0B00C77C0
```

manifest 内含全部 staging 文件及外部 Python 文件（`python.exe`、`python312.dll`、
`python3.dll`、`vcruntime140*.dll`、`_ctypes.pyd`、`libffi-8.dll`、`_hashlib.pyd`、
`libcrypto-3.dll`、`_socket.pyd`）的 SHA-256；脚本启动前逐一核对。

## 4. 运行前验证步骤（管理员 PowerShell）

```powershell
# 1) 确认无既有 ADLLTest；存在则停止，不要运行脚本
Get-LocalUser -Name ADLLTest -ErrorAction SilentlyContinue

# 2) 核对两个关键摘要（应与上文完全一致）
(Get-FileHash 'C:\ProgramData\ADLL-Account-Staging\scripts\create_adll_probe_account.ps1' -Algorithm SHA256).Hash
(Get-FileHash 'C:\ProgramData\ADLL-Account-Staging\manifest.json' -Algorithm SHA256).Hash

# 3) 确认 staging 对 Users 只读、无写权限
(Get-Acl 'C:\ProgramData\ADLL-Account-Staging').Access |
  Where-Object { $_.IdentityReference -match 'Users|Everyone' } |
  Format-Table IdentityReference,FileSystemRights,AccessControlType

# 4) 确认 Python base 对 Users 只读执行、非可写
(Get-Acl 'D:\wo\python\Python312\python.exe').Access |
  Format-Table IdentityReference,FileSystemRights,AccessControlType
```

期望：staging 中 `BUILTIN\Users` 仅 `ReadAndExecute`，无 `Write/Modify/FullControl`；
Python base 中 `Everyone` 仅 `ReadAndExecute`；`ADLLTest` 不存在。

## 5. 最终本地执行命令

在**管理员 PowerShell**中执行以下一条（`-NoProfile`；先固定 PSModulePath，再调用
staging 脚本；脚本会隐藏提示输入临时口令）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::SetEnvironmentVariable('PSModulePath','C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules','Process'); & 'C:\ProgramData\ADLL-Account-Staging\scripts\create_adll_probe_account.ps1'"
```

- 口令仅由用户在本地隐藏提示输入；不会进入脚本/日志/项目/聊天。
- 证据（ADLLTest 不可写）：`C:\ProgramData\ADLL-Account-SelfCheck\parent\evidence.json`。
- 脚本结束会询问是否删除 `ADLLTest`；若探针启动后异常，账户保留供调查。
- 若 `ADLLTest` 已存在，脚本拒绝，不覆盖/修改/删除。

## 6. 回滚/清理

- 若尚未运行：删除 staging（管理员）：
  `Remove-Item 'C:\ProgramData\ADLL-Account-Staging' -Recurse -Force`
- 若运行后：先查看 `parent\evidence.json`；按脚本提示删除 ADLLTest。
- 异常残留：
  ```powershell
  Get-LocalUser -Name ADLLTest -ErrorAction SilentlyContinue
  Get-Process -IncludeUserName -ErrorAction SilentlyContinue | Where-Object UserName -like '*\ADLLTest'
  Remove-LocalUser -Name ADLLTest
  Get-CimInstance Win32_UserProfile | Where-Object LocalPath -like '*ADLLTest*' |
    ForEach-Object { if (-not $_.Loaded) { Remove-CimInstance -InputObject $_ } }
  Get-ChildItem 'C:\ProgramData\ADLL-Account-SelfCheck' -Force
  # 仅确认无 reparse point 后，人工决定是否删除 Base/Parent/Work
  ```
- 不修改真实项目 ACL、不修改防火墙、不删除项目文件。

## 7. 仍未解决

1. **项目根 Everyone FullControl**：ADLLTest 仍可读写项目/潜在 DB；staging 只解决
   **管理员执行来源**，不解决数据隔离。生产 S10/S14 仍 **FAIL/NOT PASS**。
2. **证据自报**：account_selfcheck 在 ADLLTest 内运行；父进程复核 nonce/SID/摘要，
   但不能作为独立第三方证明。
3. **S9** 仍 NOT RUN；TEST-NET 结果不构成 allowlist PASS。
4. 本轮未执行账户创建；实际 SID/文件/网络/Job 结果等待用户运行。