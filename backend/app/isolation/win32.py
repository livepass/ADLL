"""Windows 受限 worker 原语：受限令牌 + DACL Deny + Job Object。

设计（批 8，ADR-C4 §4.0）：
- 父进程（后端）保留原用户令牌，仅通过 `CreateRestrictedToken` 派生子进程；
  restricting SIDs 使用「Users / Authenticated Users / Everyone / 专用随机 SID」。
  专用 SID 不出现在任何正常客体 ACL 中，除非显式授予（物化子集）或被显式 Deny
  （原仓库/审批 DB/用户目录/凭据）。
- DACL 读取隔离以显式 `Deny <专用 SID>` 为准；低完整性/MIC 不作为读取隔离证据。
- Job Object 仅负责进程树生命周期（kill-on-close、禁 breakaway），不是安全边界。
- 所有 ACL 修改只允许发生在显式 `sandbox_root` 之内；防止误改真实用户目录/仓库。

本模块仅 Windows；调用方须先确认 os.name == "nt"。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

try:
    import msvcrt
except ImportError:  # 非 Windows：模块仅用于类型/测试跳过，调用会显式失败
    msvcrt = None  # type: ignore[assignment]

if os.name == "nt":
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - 非 Windows 不执行隔离路径
    class _Unavailable:
        def __getattr__(self, name: str) -> "_Unavailable":
            return _Unavailable()

        def __call__(self, *args, **kwargs) -> int:
            return 0

    advapi32 = _Unavailable()  # type: ignore[assignment]
    kernel32 = _Unavailable()  # type: ignore[assignment]

TOKEN_ALL_ACCESS = 0xF01FF
TOKEN_QUERY = 0x0008
TokenUser = 1
TokenRestrictedSids = 11
DISABLE_MAX_PRIVILEGE = 0x1
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
STARTF_USESTDHANDLES = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class TOKEN_GROUPS(ctypes.Structure):
    # TOKEN_GROUPS is variable-length; 64 entries cover the four restricting
    # SIDs used here with ample headroom.
    _fields_ = [("GroupCount", wt.DWORD), ("Groups", SID_AND_ATTRIBUTES * 64)]


class TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.CreateJobObjectW.restype = wt.HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
kernel32.SetInformationJobObject.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
]
kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
kernel32.AssignProcessToJobObject.restype = wt.BOOL
kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.TerminateProcess.restype = wt.BOOL
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.GetExitCodeProcess.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi32.OpenProcessToken.restype = wt.BOOL
advapi32.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
advapi32.ConvertStringSidToSidW.restype = wt.BOOL
advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
advapi32.ConvertSidToStringSidW.restype = wt.BOOL
advapi32.GetTokenInformation.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
advapi32.GetTokenInformation.restype = wt.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p
advapi32.CreateRestrictedToken.argtypes = [
    wt.HANDLE,
    wt.DWORD,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wt.HANDLE),
]
advapi32.CreateRestrictedToken.restype = wt.BOOL
advapi32.CreateProcessAsUserW.argtypes = [
    wt.HANDLE,
    wt.LPCWSTR,
    wt.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.BOOL,
    wt.DWORD,
    ctypes.c_void_p,
    wt.LPCWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
advapi32.CreateProcessAsUserW.restype = wt.BOOL
advapi32.IsTokenRestricted.argtypes = [wt.HANDLE]
advapi32.IsTokenRestricted.restype = wt.BOOL
kernel32.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
kernel32.IsProcessInJob.restype = wt.BOOL
kernel32.ResumeThread.argtypes = [wt.HANDLE]
kernel32.ResumeThread.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
kernel32.GetProcessTimes.restype = wt.BOOL

# 运行 Python/系统 DLL 所需的公共 SID（不包含当前用户 SID）。
DEFAULT_RESTRICTING_SIDS = (
    "S-1-5-32-545",  # BUILTIN\Users
    "S-1-5-11",  # Authenticated Users
    "S-1-1-0",  # Everyone
)


def generate_restricting_sid() -> str:
    """生成仅用于本次 worker 的随机 SID（非本地账户，不可映射）。"""
    return "S-1-5-21-{}-{}-{}-{}".format(
        random.randint(1, 2**31 - 1),
        random.randint(1, 2**31 - 1),
        random.randint(1, 2**31 - 1),
        random.randint(1000, 2**31 - 1),
    )


def _token_restricted_sid_pairs(token_handle: int) -> list[tuple[str, int]]:
    groups = TOKEN_GROUPS()
    size = wt.DWORD(ctypes.sizeof(groups))
    if not advapi32.GetTokenInformation(
        token_handle,
        TokenRestrictedSids,
        ctypes.byref(groups),
        size,
        ctypes.byref(size),
    ):
        return []
    result: list[tuple[str, int]] = []
    for index in range(min(int(groups.GroupCount), 64)):
        item = groups.Groups[index]
        if not item.Sid:
            continue
        string_ptr = ctypes.c_void_p()
        if advapi32.ConvertSidToStringSidW(item.Sid, ctypes.byref(string_ptr)):
            try:
                result.append(
                    (ctypes.wstring_at(string_ptr.value), int(item.Attributes))
                )
            finally:
                kernel32.LocalFree(string_ptr)
    return result


def token_restricted_sids(token_handle: int) -> list[str]:
    """Return the child token's restricting SIDs (diagnostics only).

    IsTokenRestricted() only proves that the list is non-empty; an ACE for a
    SID that never made it into the token would still be ignored.
    """
    return [sid for sid, _ in _token_restricted_sid_pairs(token_handle)]


def token_restricted_sid_attributes(token_handle: int) -> dict[str, int]:
    """Return each restricting SID's token attributes (deny-only diagnostic)."""
    return dict(_token_restricted_sid_pairs(token_handle))


def current_user_sid() -> str:
    """Return the current process user SID (the parent account's normal SID)."""
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError("OpenProcessToken failed")
    try:
        size = wt.DWORD(0)
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        if size.value == 0:
            raise OSError("GetTokenInformation(TokenUser) returned no size")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TokenUser, buffer, size, ctypes.byref(size)
        ):
            raise OSError("GetTokenInformation(TokenUser) failed")
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        string_ptr = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(string_ptr)
        ):
            raise OSError("ConvertSidToStringSidW failed")
        try:
            return ctypes.wstring_at(string_ptr.value)
        finally:
            kernel32.LocalFree(string_ptr)
    finally:
        kernel32.CloseHandle(token)


def get_process_token_user(process_handle: int) -> str | None:
    """Return the TokenUser SID of a (possibly suspended) child process.

    This is the pre-resume identity check primitive: before `ResumeThread` the
    launcher must confirm the child really runs under the approved principal.
    Returns None when the token cannot be queried (caller must fail-closed).
    """
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wt.DWORD(0)
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        if size.value == 0:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TokenUser, buffer, size, ctypes.byref(size)
        ):
            return None
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        string_ptr = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(string_ptr)
        ):
            return None
        try:
            return ctypes.wstring_at(string_ptr.value)
        finally:
            kernel32.LocalFree(string_ptr)
    finally:
        kernel32.CloseHandle(token)


def get_process_creation_time(process_handle: int) -> int | None:
    """Return the child's creation FILETIME (as int) for pre-resume binding.

    Combined with the PID this lets the launcher confirm it is inspecting the
    very process it just created (no PID-reuse confusion).
    """
    create = ctypes.c_ulonglong()
    exit_t = ctypes.c_ulonglong()
    kernel_t = ctypes.c_ulonglong()
    user_t = ctypes.c_ulonglong()
    if not kernel32.GetProcessTimes(
        process_handle,
        ctypes.byref(create),
        ctypes.byref(exit_t),
        ctypes.byref(kernel_t),
        ctypes.byref(user_t),
    ):
        return None
    return int(create.value)


class RestrictedToken:
    def __init__(self, handle: int, restricting_sid: str) -> None:
        self.handle = handle
        self.restricting_sid = restricting_sid

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "RestrictedToken":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def create_restricted_token(restricting_sid: str | None = None) -> RestrictedToken:
    sid = restricting_sid or generate_restricting_sid()
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_ALL_ACCESS, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    sids = [*DEFAULT_RESTRICTING_SIDS, sid]
    array = (SID_AND_ATTRIBUTES * len(sids))()
    pointers: list[ctypes.c_void_p] = []
    for index, value in enumerate(sids):
        pointer = ctypes.c_void_p()
        if not advapi32.ConvertStringSidToSidW(value, ctypes.byref(pointer)):
            kernel32.CloseHandle(token)
            raise ctypes.WinError(ctypes.get_last_error())
        pointers.append(pointer)
        array[index].Sid = pointer
        array[index].Attributes = 0

    restricted = wt.HANDLE()
    ok = advapi32.CreateRestrictedToken(
        token,
        DISABLE_MAX_PRIVILEGE,
        0,
        None,
        0,
        None,
        len(sids),
        array,
        ctypes.byref(restricted),
    )
    kernel32.CloseHandle(token)
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return RestrictedToken(restricted.value, sid)


def build_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """最小环境块：不继承父进程的凭据/Python 路径/代理配置。"""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env = {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "PATH": f"{system_root}\\System32;{system_root}",
        "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    if extra:
        env.update({key: value for key, value in extra.items() if value is not None})
    return env


def _environment_block(env: dict[str, str]) -> ctypes.c_wchar_p:
    entries = "\0".join(f"{key}={value}" for key, value in sorted(env.items()))
    return ctypes.c_wchar_p(entries + "\0\0")


class JobObject:
    """kill-on-close 的进程树容器；不设置 breakaway 标志。"""

    def __init__(self) -> None:
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process_handle: int) -> None:
        if not kernel32.AssignProcessToJobObject(self.handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        if self.handle:
            kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "JobObject":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class RestrictedProcess:
    pid: int
    handle: int
    token: RestrictedToken
    job: JobObject
    token_restricted: bool
    restricting_sids: list[str] = field(default_factory=list)
    restricting_sid_attributes: dict[str, int] = field(default_factory=dict)
    # CREATE_SUSPENDED 时保留主线程句柄，供恢复前复核后 ResumeThread。
    thread_handle: int | None = None
    # 恢复前身份检查是否已通过（由 pre_resume_check 在 ok 时置位）。
    _pre_resume_ok: bool = field(default=False, init=False, repr=False)

    def wait(self, timeout_ms: int) -> int:
        result = kernel32.WaitForSingleObject(self.handle, timeout_ms)
        if result == 0x00000102:  # WAIT_TIMEOUT
            self.job.terminate()
            raise TimeoutError("restricted process timed out")
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)

    def resume(self) -> None:
        """Resume a CREATE_SUSPENDED process — only after a passing pre-resume check.

        `pre_resume_check()` must have returned `ok=True` (which sets the
        internal gate) before `resume()` is called. Resuming a suspended worker
        whose identity has not been confirmed is forbidden and raises here.
        """
        if self.thread_handle is None:
            # 非挂起创建（suspended=False）：无恢复步骤，直接返回。
            return
        if not self._pre_resume_ok:
            raise RuntimeError("resume denied: pre-resume identity check not passed")
        # 恢复失败（如已退出）返回 0xFFFFFFFF；主线程不复用，失败即视为异常。
        if kernel32.ResumeThread(self.thread_handle) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        # 先关闭 Job（kill-on-close）再释放进程句柄；确保子进程树不遗留。
        self.job.close()
        if self.thread_handle is not None:
            kernel32.CloseHandle(self.thread_handle)
            self.thread_handle = None
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None
        self.token.close()


def spawn_restricted(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    restricting_sid: str | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    suspended: bool = False,
) -> RestrictedProcess:
    """Spawn the worker under a restricted token inside a kill-on-close Job.

    `suspended=True` creates the process with CREATE_SUSPENDED and leaves the
    primary thread suspended. The caller MUST run `pre_resume_check()` and act
    on its result before calling `process.resume()`; resuming without a passing
    check violates the S9-1 identity gate. Default False preserves the existing
    non-suspended behaviour used by probe/worker launch paths.
    """
    token = create_restricted_token(restricting_sid)
    job = JobObject()
    startup = STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    opened: list[int] = []
    handles: list[int] = []
    creation_flags = CREATE_UNICODE_ENVIRONMENT
    if suspended:
        creation_flags |= CREATE_SUSPENDED
    try:
        if stdout_path is not None or stderr_path is not None:
            std_out = stdout_path or stderr_path
            std_err = stderr_path or stdout_path
            for target in (std_out, std_err):
                fd = os.open(
                    str(target), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o666
                )
                os.set_inheritable(fd, True)
                opened.append(fd)
                handles.append(msvcrt.get_osfhandle(fd))
            stdin_fd = os.open(os.devnull, os.O_RDONLY)
            os.set_inheritable(stdin_fd, True)
            opened.append(stdin_fd)
            startup.dwFlags |= STARTF_USESTDHANDLES
            startup.hStdInput = msvcrt.get_osfhandle(stdin_fd)
            startup.hStdOutput = handles[0]
            startup.hStdError = handles[1]
        process_info = PROCESS_INFORMATION()
        command_line = subprocess.list2cmdline(command)
        buffer = ctypes.create_unicode_buffer(command_line)
        env_block = _environment_block(env or build_environment())
        ok = advapi32.CreateProcessAsUserW(
            token.handle,
            None,
            buffer,
            None,
            None,
            bool(opened),
            creation_flags,
            ctypes.cast(env_block, ctypes.c_void_p),
            str(cwd),
            ctypes.byref(startup),
            ctypes.byref(process_info),
        )
        if not ok:
            error = ctypes.get_last_error()
            job.close()
            token.close()
            raise ctypes.WinError(error)
    finally:
        for fd in opened:
            os.close(fd)
    # 纳管失败必须 terminate + wait：仅关闭未纳管进程句柄会遗留失控进程树。
    try:
        job.assign(process_info.hProcess)
    except OSError:
        # 先终止进程（及其可能的子进程），再等待其退出，最后释放所有句柄。
        try:
            kernel32.TerminateProcess(process_info.hProcess, 1)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
        finally:
            job.close()
            token.close()
            kernel32.CloseHandle(process_info.hThread)
            kernel32.CloseHandle(process_info.hProcess)
        raise
    thread_handle = process_info.hThread if suspended else None
    if not suspended:
        kernel32.CloseHandle(process_info.hThread)
    process_token = wt.HANDLE()
    token_restricted = False
    restricted_sids: list[str] = []
    restricted_sid_attrs: dict[str, int] = {}
    if advapi32.OpenProcessToken(
        process_info.hProcess, TOKEN_QUERY, ctypes.byref(process_token)
    ):
        try:
            token_restricted = bool(advapi32.IsTokenRestricted(process_token))
            if token_restricted:
                restricted_sids = token_restricted_sids(process_token)
                restricted_sid_attrs = token_restricted_sid_attributes(process_token)
        finally:
            kernel32.CloseHandle(process_token)
    if not token_restricted:
        # 未能证明子进程使用受限令牌 → 立即失败，绝不降级运行。
        job.terminate()
        job.close()
        if thread_handle is not None:
            kernel32.CloseHandle(thread_handle)
        token.close()
        kernel32.CloseHandle(process_info.hProcess)
        raise OSError("child process token is not restricted")
    return RestrictedProcess(
        pid=int(process_info.dwProcessId),
        handle=process_info.hProcess,
        token=token,
        job=job,
        token_restricted=True,
        restricting_sids=restricted_sids,
        restricting_sid_attributes=restricted_sid_attrs,
        thread_handle=thread_handle,
    )


@dataclass(frozen=True)
class PreResumeCheck:
    """Evidence the launcher collects while the worker is still suspended.

    `ok` is True only when **every** expected binding is verified:
    - TokenUser SID == expected_token_user_sid（批准主体）
    - token is restricted and carries the expected restricting SID
    - creation time / pid are present（防止 PID 复用混淆）
    - the process is confirmed inside the expected Job（`in_job`）
    - program identity matches `expected_program_sha256`（若提供）

    On non-ok the caller must terminate + wait (not resume); the mismatch reason
    is reported in `fail_reasons` for diagnostics.
    """
    pid: int
    token_user_sid: str | None
    creation_time: int | None
    token_restricted: bool
    restricting_sids: tuple[str, ...] = ()
    expected_token_user_sid: str | None = None
    expected_restricting_sid: str | None = None
    expected_program_sha256: str | None = None
    program_sha256: str | None = None
    in_job: bool = False
    fail_reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.fail_reasons


def pre_resume_check(
    process: RestrictedProcess,
    *,
    expected_token_user_sid: str | None,
    expected_restricting_sid: str | None,
    expected_program_sha256: str | None = None,
    program_sha256: str | None = None,
) -> PreResumeCheck:
    """Collect + **enforce** identity evidence before ResumeThread (S9-1 gate).

    The expected bindings are explicit parameters; a missing/mismatched token
    user SID or restricting SID makes `ok` False. On `ok`, the internal resume
    gate on `process` is opened (so `process.resume()` will succeed); otherwise
    the caller must `process.job.terminate()` + `process.close()`.

    Read-only with respect to the process; never resumes on its own.
    """
    fail: list[str] = []
    token_user_sid = get_process_token_user(process.handle)
    creation_time = get_process_creation_time(process.handle)

    if token_user_sid is None:
        fail.append("token_user_unavailable")
    elif expected_token_user_sid is not None and token_user_sid != expected_token_user_sid:
        fail.append("token_user_mismatch")

    if creation_time is None:
        fail.append("creation_time_unavailable")

    if not process.token_restricted:
        fail.append("token_not_restricted")

    if expected_restricting_sid is not None and expected_restricting_sid not in process.restricting_sids:
        fail.append("restricting_sid_mismatch")

    in_job = is_process_in_job(process.pid, process.job.handle)
    if not in_job:
        fail.append("not_in_job")

    if expected_program_sha256 is not None:
        if program_sha256 is None or program_sha256 != expected_program_sha256:
            fail.append("program_identity_mismatch")

    check = PreResumeCheck(
        pid=process.pid,
        token_user_sid=token_user_sid,
        creation_time=creation_time,
        token_restricted=process.token_restricted,
        restricting_sids=tuple(process.restricting_sids),
        expected_token_user_sid=expected_token_user_sid,
        expected_restricting_sid=expected_restricting_sid,
        expected_program_sha256=expected_program_sha256,
        program_sha256=program_sha256,
        in_job=in_job,
        fail_reasons=tuple(fail),
    )
    if check.ok:
        process._pre_resume_ok = True  # noqa: SLF001 — 同一模块内合法置位
    return check


def is_process_alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_process_in_job(pid: int, job_handle: int | None = None) -> bool:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        result = wt.BOOL()
        if not kernel32.IsProcessInJob(handle, job_handle, ctypes.byref(result)):
            return False
        return bool(result.value)
    finally:
        kernel32.CloseHandle(handle)


# ---- DACL 管理（仅限 sandbox_root 之内） ----


def _assert_inside(path: Path, sandbox_root: Path) -> None:
    root = os.path.normcase(os.path.realpath(sandbox_root))
    target = os.path.normcase(os.path.realpath(path))
    if target == root:
        raise ValueError("refusing to ACL the sandbox root itself")
    if os.path.commonpath([root, target]) != root:
        raise ValueError(f"ACL target outside sandbox root: {path}")


def error_details(exc: Exception) -> dict:
    """Only structured diagnostics; never copy commands, payloads or credentials."""
    return {
        "type": type(exc).__name__,
        "winerror": getattr(exc, "winerror", None),
        "errno": getattr(exc, "errno", None),
        "diagnostic": getattr(exc, "diagnostic", None),
    }


class AclOperationError(RuntimeError):
    def __init__(self, operation: str, diagnostic: dict):
        self.diagnostic = {"operation": operation, **diagnostic}
        super().__init__(f"ACL operation failed: {operation}")


def _powershell(script: str, operation: str = "acl") -> str:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "$ErrorActionPreference='Stop'; $adllPhase='enter'; try { " + script +
            " } catch { [Console]::Error.WriteLine((@{"
            "phase=$adllPhase;"
            "privilege_name=$_.Exception.PrivilegeName;"
            "inner_exception_type=if ($_.Exception.InnerException) {$_.Exception.InnerException.GetType().FullName} else {$null};"
            "exception_type=$_.Exception.GetType().FullName;"
            "hresult=$_.Exception.HResult;"
            "category=[string]$_.CategoryInfo.Category"
            "} | ConvertTo-Json -Compress)); exit 1 }",
        ],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        try:
            detail = json.loads(result.stderr.decode("utf-8"))
            detail = {k: detail.get(k) for k in ("exception_type", "hresult", "category", "phase", "privilege_name", "inner_exception_type")}
        except (ValueError, AttributeError):
            detail = {"diagnostic_unavailable": True}
        if (
            operation == "restore_dacl"
            and detail.get("inner_exception_type") == "System.UnauthorizedAccessException"
        ):
            # ReadPermissions (READ_CONTROL) is part of FileSystemRights.Read;
            # a Deny Read/FullControl ACE on the caller's own SID therefore
            # blocks SetAccessControl even though the caller is the owner.
            detail["hint"] = "restore_requires_read_control_and_write_dac"
        raise AclOperationError(operation, {"exit_code": result.returncode, **detail})
    return result.stdout.decode("utf-8", "replace").strip()


def get_sddl(path: Path) -> str:
    escaped = str(path).replace("'", "''")
    kind = "Directory" if path.is_dir() else "File"
    return _powershell(
        f"$adllPhase='read_acl'; [IO.{kind}]::GetAccessControl('{escaped}',"
        "[System.Security.AccessControl.AccessControlSections]::Access).GetSecurityDescriptorSddlForm("
        "[System.Security.AccessControl.AccessControlSections]::Access)", "get_dacl")


def restore_sddl(path: Path, sddl: str, *, is_directory: bool | None = None) -> None:
    escaped = str(path).replace("'", "''")
    escaped_sddl = sddl.replace("'", "''")
    kind = "Directory" if (path.is_dir() if is_directory is None else is_directory) else "File"
    _powershell(
        "$adllPhase='construct_dacl'; $acl = New-Object System.Security.AccessControl.%sSecurity; "
        "$adllPhase='set_dacl_in_memory'; "
        "$acl.SetSecurityDescriptorSddlForm('%s', [System.Security.AccessControl.AccessControlSections]::Access); "
        "$adllPhase='persist_acl'; "
        "[IO.%s]::SetAccessControl('%s', $acl)"
        % (kind, escaped_sddl, kind, escaped), "restore_dacl"
    )


@dataclass
class AclChange:
    path: Path
    sddl: str
    is_directory: bool | None = None


def _acl_rule(
    path: Path,
    sid: str,
    sandbox_root: Path,
    *,
    allow: bool,
    rights: str = "FullControl",
    root_allowed: bool = False,
) -> AclChange:
    root = os.path.normcase(os.path.realpath(sandbox_root))
    target = os.path.normcase(os.path.realpath(path))
    if target == root and not root_allowed:
        raise ValueError("refusing to ACL the sandbox root itself")
    if os.path.commonpath([root, target]) != root:
        raise ValueError(f"ACL target outside sandbox root: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    sddl = get_sddl(path)
    is_directory = path.is_dir()
    object_kind = "Directory" if is_directory else "File"
    escaped = str(path).replace("'", "''")
    inheritance = "ContainerInherit,ObjectInherit" if path.is_dir() else "None"
    kind = "Allow" if allow else "Deny"
    script = (
        "$adllPhase='construct_sid'; $sid = New-Object System.Security.Principal.SecurityIdentifier('%s'); "
        "$adllPhase='read_acl'; $acl = [IO.%s]::GetAccessControl('%s', [System.Security.AccessControl.AccessControlSections]::Access); "
        "$adllPhase='construct_rule'; "
        "$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("
        "$sid, '%s', '%s', 'None', '%s'); "
        "$adllPhase='add_rule_in_memory'; $acl.AddAccessRule($rule); "
        "$adllPhase='persist_acl'; "
        "[IO.%s]::SetAccessControl('%s', $acl)"
        % (sid, object_kind, escaped, rights, inheritance, kind, object_kind, escaped)
    )
    _powershell(script, "allow_dacl" if allow else "deny_dacl")
    return AclChange(path=path, sddl=sddl, is_directory=is_directory)


def deny_sid(path: Path, sid: str, sandbox_root: Path) -> AclChange:
    """对 path 添加 `Deny <sid> FullControl`；返回可回滚的原始 SDDL。"""
    return _acl_rule(path, sid, sandbox_root, allow=False)


def allow_sid(
    path: Path,
    sid: str,
    sandbox_root: Path,
    *,
    rights: str = "FullControl",
    root_allowed: bool = True,
) -> AclChange:
    """对 sandbox 内客体显式授予受限 SID（仅用于物化子集/sandbox）。"""
    return _acl_rule(
        path, sid, sandbox_root, allow=True, rights=rights, root_allowed=root_allowed
    )


def restore_acl(changes: list[AclChange]) -> None:
    failures = []
    for change in reversed(changes):
        try:
            restore_sddl(change.path, change.sddl, is_directory=change.is_directory)
        except Exception as exc:  # noqa: BLE001
            failures.append({"path": str(change.path), **error_details(exc)})
    if failures:
        raise AclOperationError("rollback", {"failures": failures})
