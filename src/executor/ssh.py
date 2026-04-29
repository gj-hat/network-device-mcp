"""SSH 执行层模块。

使用 netmiko 连接网络设备并执行命令，通过 asyncio.to_thread 实现异步。
并发上限通过 asyncio.Semaphore 控制。
"""

import asyncio

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from src.core.config import DEVICE_TYPE_MAP, MAX_CONCURRENCY, SSH_TIMEOUT

# 模块级信号量，控制全局 SSH 并发连接数
_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

# 需要使用 send_command_timing 的 netmiko device_type 集合
# 这些设备的 prompt 匹配容易误判（输出中含主机名导致提前截断）
_TIMING_DEVICE_TYPES: set[str] = {"hp_comware", "huawei_vrp"}


class SSHExecutionError(Exception):
    """SSH 执行失败时抛出的异常。"""


async def execute(
    *,
    host: str,
    port: int,
    device_type: str,
    username: str,
    password: str,
    command: str,
) -> str:
    """在目标设备上执行一条命令并返回原始输出。

    Args:
        host: 设备 IP 地址
        port: SSH 端口
        device_type: 本系统的设备类型（cisco/huawei/h3c）
        username: SSH 用户名
        password: SSH 密码
        command: 拼装后的最终命令

    Returns:
        设备返回的原始文本输出

    Raises:
        SSHExecutionError: 连接失败、认证失败、超时等
    """
    netmiko_device_type = DEVICE_TYPE_MAP.get(device_type)
    if not netmiko_device_type:
        raise SSHExecutionError(f"不支持的设备类型: {device_type}")

    device_params = {
        "device_type": netmiko_device_type,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "timeout": SSH_TIMEOUT,
        "read_timeout_override": SSH_TIMEOUT,
        "conn_timeout": SSH_TIMEOUT,
    }

    async with _semaphore:
        try:
            output = await asyncio.to_thread(_execute_blocking, device_params, command)
        except NetmikoAuthenticationException:
            raise SSHExecutionError(f"认证失败: {host}:{port}")
        except NetmikoTimeoutException:
            raise SSHExecutionError(f"连接超时: {host}:{port}（超时 {SSH_TIMEOUT}s）")
        except OSError as e:
            raise SSHExecutionError(f"设备不可达: {host}:{port} — {e}")
        except Exception as e:
            raise SSHExecutionError(f"SSH 执行异常: {host}:{port} — {type(e).__name__}: {e}")

    return output


async def execute_multi(
    *,
    host: str,
    port: int,
    device_type: str,
    username: str,
    password: str,
    commands: list[str],
) -> list[dict]:
    """在目标设备上通过一次 SSH 连接顺序执行多条命令。

    Args:
        host: 设备 IP 地址
        port: SSH 端口
        device_type: 本系统的设备类型
        username: SSH 用户名
        password: SSH 密码
        commands: 拼装后的最终命令列表

    Returns:
        每条命令的执行结果列表，每项为 {"command": str, "success": bool, "output": str, "error": str}

    Raises:
        SSHExecutionError: 连接建立阶段的异常（认证失败、超时、不可达）
    """
    netmiko_device_type = DEVICE_TYPE_MAP.get(device_type)
    if not netmiko_device_type:
        raise SSHExecutionError(f"不支持的设备类型: {device_type}")

    device_params = {
        "device_type": netmiko_device_type,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "timeout": SSH_TIMEOUT,
        "read_timeout_override": SSH_TIMEOUT,
        "conn_timeout": SSH_TIMEOUT,
    }

    async with _semaphore:
        try:
            results = await asyncio.to_thread(
                _execute_multi_blocking, device_params, commands
            )
        except NetmikoAuthenticationException:
            raise SSHExecutionError(f"认证失败: {host}:{port}")
        except NetmikoTimeoutException:
            raise SSHExecutionError(f"连接超时: {host}:{port}（超时 {SSH_TIMEOUT}s）")
        except OSError as e:
            raise SSHExecutionError(f"设备不可达: {host}:{port} — {e}")
        except Exception as e:
            raise SSHExecutionError(f"SSH 执行异常: {host}:{port} — {type(e).__name__}: {e}")

    return results


def _send_command(conn, command: str, device_type: str) -> str:
    """根据设备类型选择合适的命令发送方式。

    hp_comware / huawei_vrp 使用 send_command_timing（基于时间判断输出结束），
    避免 prompt 误判导致输出截断或串流。
    其他设备使用 send_command（基于 prompt 匹配，更精确）。
    """
    if device_type in _TIMING_DEVICE_TYPES:
        return conn.send_command_timing(command, delay_factor=2)
    return conn.send_command(command, read_timeout=SSH_TIMEOUT)


def _execute_blocking(device_params: dict, command: str) -> str:
    """同步执行单条 SSH 命令（在线程中运行）。"""
    with ConnectHandler(**device_params) as conn:
        output = _send_command(conn, command, device_params["device_type"])
    return output


def _execute_multi_blocking(device_params: dict, commands: list[str]) -> list[dict]:
    """同步执行多条 SSH 命令，共用一个连接（在线程中运行）。

    单条命令执行异常不中断连接，继续执行后续命令。
    """
    device_type = device_params["device_type"]
    results = []
    with ConnectHandler(**device_params) as conn:
        for cmd in commands:
            try:
                output = _send_command(conn, cmd, device_type)
                results.append({
                    "command": cmd,
                    "success": True,
                    "output": output,
                    "error": "",
                })
            except Exception as e:
                results.append({
                    "command": cmd,
                    "success": False,
                    "output": "",
                    "error": f"{type(e).__name__}: {e}",
                })
    return results
