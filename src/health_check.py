"""设备健康检测模块。

SSH 连接建立后、业务命令执行前，检测设备 CPU 使用率和在线用户数。
任一指标超阈值则拒绝执行，解析失败则跳过检测继续执行。

本模块是系统中唯一需要解析命令输出的地方，业务命令输出一律原样返回。
"""

import re
from dataclasses import dataclass, field

from src.core.config import (
    HEALTH_CHECK_CPU_CMD_ID,
    HEALTH_CHECK_CPU_THRESHOLD,
    HEALTH_CHECK_ENABLED,
    HEALTH_CHECK_USER_THRESHOLD,
    HEALTH_CHECK_USERS_CMD_ID,
)
from src.commands.registry import resolve_and_validate


@dataclass
class HealthCheckResult:
    """健康检测结果。"""

    passed: bool = True
    warning: str = ""
    details: dict = field(default_factory=dict)


def is_enabled() -> bool:
    """是否启用健康检测。"""
    return HEALTH_CHECK_ENABLED


def get_check_commands(device_type: str) -> list[tuple[str, str]]:
    """获取指定设备类型的健康检测命令列表。

    Returns:
        [(command_id, final_command), ...] 检测命令列表
        如果命令解析失败则返回空列表（不阻断业务）
    """
    commands = []
    for cmd_id in (HEALTH_CHECK_CPU_CMD_ID, HEALTH_CHECK_USERS_CMD_ID):
        try:
            final_cmd = resolve_and_validate(device_type, cmd_id)
            commands.append((cmd_id, final_cmd))
        except Exception:
            # 命令不存在或解析失败，跳过该项检测
            pass
    return commands


def evaluate(
    device_type: str,
    results: list[tuple[str, str]],
) -> HealthCheckResult:
    """评估健康检测命令的输出结果。

    Args:
        device_type: 本系统设备类型
        results: [(command_id, output), ...] 检测命令执行结果

    Returns:
        HealthCheckResult
    """
    details = {}
    warnings = []

    for cmd_id, output in results:
        if cmd_id == HEALTH_CHECK_CPU_CMD_ID:
            cpu = _parse_cpu(device_type, output)
            if cpu is None:
                warnings.append(f"CPU 检测输出解析失败，已跳过")
            else:
                details["cpu_percent"] = cpu
                if cpu > HEALTH_CHECK_CPU_THRESHOLD:
                    return HealthCheckResult(
                        passed=False,
                        details={"cpu_percent": cpu},
                        warning=f"设备 CPU 过载: {cpu}%（阈值 {HEALTH_CHECK_CPU_THRESHOLD}%）",
                    )

        elif cmd_id == HEALTH_CHECK_USERS_CMD_ID:
            users = _parse_users(device_type, output)
            if users is None:
                warnings.append(f"在线用户检测输出解析失败，已跳过")
            else:
                details["online_users"] = users
                if users > HEALTH_CHECK_USER_THRESHOLD:
                    return HealthCheckResult(
                        passed=False,
                        details={"online_users": users},
                        warning=f"设备在线用户过多: {users}（阈值 {HEALTH_CHECK_USER_THRESHOLD}）",
                    )

    return HealthCheckResult(
        passed=True,
        warning="; ".join(warnings) if warnings else "",
        details=details,
    )


# ── CPU 解析 ─────────────────────────────────────────────────


def _parse_cpu(device_type: str, output: str) -> int | None:
    """从命令输出中提取 CPU 使用率百分比。

    Returns:
        CPU 使用率整数（0-100），解析失败返回 None
    """
    if not output or not output.strip():
        return None

    try:
        match device_type:
            case "cisco":
                # "CPU utilization for five seconds: 25%/0%"
                m = re.search(r"five seconds:\s*(\d+)%", output)
                return int(m.group(1)) if m else None

            case "cisco_asa":
                # "CPU utilization for 5 seconds = 10%"
                m = re.search(r"5 seconds\s*=\s*(\d+)%", output)
                return int(m.group(1)) if m else None

            case "cisco_nxos":
                # "CPU states  :   2.0% user,   1.0% kernel,  97.0% idle"
                # 或 "cpuUsage5sec: 5.00%"
                m = re.search(r"(\d+(?:\.\d+)?)%\s*idle", output)
                if m:
                    return 100 - int(float(m.group(1)))
                m = re.search(r"cpuUsage5sec:\s*(\d+(?:\.\d+)?)%", output)
                return int(float(m.group(1))) if m else None

            case "huawei" | "h3c":
                # "CPU Usage : 25%"
                # 或 "CPU usage: 25%"
                # 或 "cpu-usage : 3%"
                m = re.search(r"[Cc][Pp][Uu]\s*[Uu]sage\s*:?\s*(\d+)%", output)
                if m:
                    return int(m.group(1))
                # 备选：提取第一个百分比数值
                m = re.search(r"(\d+)%", output)
                return int(m.group(1)) if m else None

            case "fortinet":
                # "CPU: 15%"
                m = re.search(r"CPU:\s*(\d+)%", output)
                return int(m.group(1)) if m else None

            case "aruba":
                # "CPU Utilization: 25%"
                m = re.search(r"[Cc][Pp][Uu]\s*[Uu]tilization:?\s*(\d+)%", output)
                if m:
                    return int(m.group(1))
                m = re.search(r"(\d+)%", output)
                return int(m.group(1)) if m else None

            case "juniper":
                # "Idle    95 percent" → CPU = 100 - 95 = 5
                # 或 "CPU utilization: 10 percent"
                m = re.search(r"[Ii]dle\s+(\d+)\s*percent", output)
                if m:
                    return 100 - int(m.group(1))
                m = re.search(r"[Uu]tilization:?\s*(\d+)\s*percent", output)
                return int(m.group(1)) if m else None

            case "ruijie":
                # "CPU utilization in five seconds: 10%"
                m = re.search(r"(\d+)%", output)
                return int(m.group(1)) if m else None

            case "ruckus":
                # 类似 Cisco 格式
                m = re.search(r"(\d+)%", output)
                return int(m.group(1)) if m else None

            case _:
                # 通用兜底：取第一个百分比
                m = re.search(r"(\d+)%", output)
                return int(m.group(1)) if m else None
    except (ValueError, AttributeError):
        return None


# ── 用户数解析 ────────────────────────────────────────────────


def _parse_users(device_type: str, output: str) -> int | None:
    """从命令输出中提取在线用户数。

    Returns:
        在线用户数整数，解析失败返回 None
    """
    if not output or not output.strip():
        return None

    try:
        match device_type:
            case "cisco" | "cisco_nxos" | "ruijie" | "ruckus":
                # show users: 每行一个活跃会话，跳过标题行
                # 典型格式：
                # Line       User       Host(s)              Idle       Location
                # * 0 con 0             idle                 00:00:00
                #   2 vty 0  admin      idle                 00:02:15  10.1.1.1
                lines = output.strip().splitlines()
                # 过滤掉空行和标题行（包含 "Line" 关键词或全是 - 分隔线）
                user_lines = [
                    l for l in lines
                    if l.strip()
                    and not re.match(r"^\s*Line\s", l, re.IGNORECASE)
                    and not re.match(r"^[\s\-]+$", l)
                ]
                return len(user_lines) if user_lines else 0

            case "cisco_asa":
                # show curpriv: 只有当前用户，返回固定 1
                # 实际 ASA 没有好的查看所有在线用户数的命令
                # 可通过其他方式判断，这里简化为始终通过
                return 1

            case "huawei" | "h3c":
                # display users 输出格式：
                #   Idx  Line     Idle       Time              Pid     Type
                #   10   VTY 0    00:01:30   May 14 17:40:52   2715182 SSH
                # + 11   VTY 1    00:00:08   May 14 17:42:13   2715226 SSH
                # Following are more details.
                # ...
                # 只匹配会话行：可选 +/F 前缀 + 数字索引 + VTY/AUX/CON
                lines = output.strip().splitlines()
                user_lines = [
                    l for l in lines
                    if re.match(r"^\s*[+F]?\s*\d+\s+(VTY|AUX|CON|TTY)\s", l)
                ]
                return len(user_lines) if user_lines else 0

            case "fortinet":
                # get system info admin: 列出管理会话
                lines = output.strip().splitlines()
                return max(len(lines) - 1, 0)  # 减去标题行

            case "aruba":
                # show loginsessions: 列出登录会话
                lines = output.strip().splitlines()
                user_lines = [
                    l for l in lines
                    if l.strip()
                    and not re.match(r"^\s*[-=]+\s*$", l)
                    and not re.match(r"^\s*(User|Session)\s", l, re.IGNORECASE)
                ]
                return len(user_lines) if user_lines else 0

            case "juniper":
                # show system users: 类似 Unix who 输出
                lines = output.strip().splitlines()
                # 跳过第一行（标题 "USER ..."）
                user_lines = [
                    l for l in lines[1:]
                    if l.strip() and not re.match(r"^\s*$", l)
                ]
                return len(user_lines) if user_lines else 0

            case _:
                # 通用：数非空行 - 1（假设第一行是标题）
                lines = [l for l in output.strip().splitlines() if l.strip()]
                return max(len(lines) - 1, 0)
    except (ValueError, AttributeError):
        return None
