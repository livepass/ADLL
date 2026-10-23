"""受限隔离组件（Windows）：令牌、Job Object、探针与 worker。"""
from .win32 import (
    AclChange,
    JobObject,
    RestrictedProcess,
    allow_sid,
    create_restricted_token,
    deny_sid,
    generate_restricting_sid,
    is_process_alive,
    is_process_in_job,
    restore_acl,
    spawn_restricted,
)

__all__ = [
    "AclChange",
    "JobObject",
    "RestrictedProcess",
    "allow_sid",
    "create_restricted_token",
    "deny_sid",
    "generate_restricting_sid",
    "is_process_alive",
    "is_process_in_job",
    "restore_acl",
    "spawn_restricted",
]