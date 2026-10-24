# S9 部署位置可行性报告（只读预检）

**日期**：2026-10-24　**状态**：只读评估，不决定最终宿主，保留人工选择。

## 1. 本机实测（只读）

| 项 | 值 |
|---|---|
| 系统 | Windows 11 家庭中文版 10.0.22000（21H2，build 22000），64 位 |
| 型号 | LENOVO 82NC |
| CPU | i5-11320H，4C8T |
| 内存 | 15.8 GiB 总量，检查时空闲约 2.3 GiB |
| 存储 | C 剩 32.2 GiB；D 剩 124 GiB |
| HypervisorPresent | True |
| CPU 虚拟化字段 | VMMonitorModeExtensions=False、SLAT=False、VirtualizationFirmwareEnabled=False |
| Hyper-V 角色 | Disabled |
| HypervisorPlatform / VirtualMachinePlatform / WSL | Enabled |
| vmms 服务 | Running |

## 2. 判读

- **Windows 家庭版不支持 Hyper-V 角色**（微软官方）；本机无法直接作为完整 Hyper-V 部署环境。
- `HypervisorPresent=True` 与 CPU 虚拟化字段 False 矛盾，属 WMI 在部分固件上的误报；
  **不能据此断言硬件不支持虚拟化，也不能认定完整 Hyper-V 可部署**。
- 空闲内存仅 2.3 GiB，低于 Worker VM 估算需求（4–6 GiB）；本机当前不适合承载。

## 3. 三条路线比较

| 路线 | 可行性 | 判定 |
|---|---|---|
| 本机部署（升级到支持 Hyper-V 的版本/组件） | 需升级系统版本、释放内存、确认固件虚拟化；家庭版不支持 Hyper-V 角色 | **NO-GO（当前）**；升级后 CONDITIONAL GO |
| 独立 Windows 主机 | 可完整安装 Hyper-V/虚拟化，专用网络 + 固定出口最可控 | **CONDITIONAL GO**（需选型：CPU 支持虚拟化、内存 ≥8GiB、Windows Pro/Server 许可、专用网卡） |
| 云端 Windows VM | 无需本地硬件/许可自建；网络隔离依赖云 VPC 默认拒绝 + 安全组 | **CONDITIONAL GO**（需确认云 VPC 出站策略、成本、数据地域合规、是否接受云端承载 Worker） |

## 4. 结论

- 本机：**NO-GO（当前版本与资源）**；不假设一定能在本机跑。
- 独立主机 / 云 VM：**CONDITIONAL GO**，需进一步确认资源、许可、网络与成本后由人工选择。
- 本轮不决定最终宿主。

## 5. 待人工确认项

1. 是否接受升级本机系统或改用独立主机/云 VM。
2. 独立主机的 CPU/内存/许可与专用网卡；或云 VM 的地域、VPC、成本与数据合规。
3. 出口软件（egress relay）、虚拟交换机与控制通道的具体选型。
