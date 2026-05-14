"""SSH 执行层模块。

使用 netmiko 连接网络设备并执行命令，通过 asyncio.to_thread 实现异步。
并发上限通过 asyncio.Semaphore 控制。

提供两种使用方式：
1. 高层接口 execute() / execute_multi() — 封装完整流程（向后兼容）
2. ssh_session 上下文管理器 — 暴露连接对象，支持健康检测等中间逻辑插入
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
_TIMING_DEVICE_TYPES: set[str] = {"hp_comware", "huawei_vrp", "aruba_os"}


class SSHExecutionError(Exception):
    """SSH 执行失败时抛出的异常。"""


# ── 上下文管理器（暴露连接对象）────────────────────────────────


@asynccontextmanager
async def ssh_session(
    *,
    host: str,
    port: int,
    device_type: str,
    username: str,
    password: str,
) -> AsyncGenerator[tuple, None]:
    """SSH 连接上下文管理器。

    在 semaphore 保护下建立连接，退出时自动断连并释放信号量。
    供 handlers 编排「连接→检测→执行→断连」流程。

    Yields:
        (conn, netmiko_device_type): netmiko 连接对象和设备类型字符串

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
            conn = await asyncio.to_thread(_connect_blocking, device_params)
        except NetmikoAuthenticationException:
            raise SSHExecutionError(f"认证失败: {host}:{port}")
        except NetmikoTimeoutException:
            raise SSHExecutionError(f"连接超时: {host}:{port}（超时 {SSH_TIMEOUT}s）")
        except OSError as e:
            raise SSHExecutionError(f"设备不可达: {host}:{port} — {e}")
        except Exception as e:
            raise SSHExecutionError(f"SSH 执行异常: {host}:{port} — {type(e).__name__}: {e}")

        try:
            yield conn, netmiko_device_type
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass  # 断连失败不影响业务


def execute_on_connection(conn, command: str, netmiko_device_type: str) -> str:
    """在已有连接上执行单条命令。

    注意：此函数是同步的，在 asyncio 环境中需配合 to_thread 使用，
    或在 ssh_session 的 yield 后直接调用（因为整个上下文已在 to_thread 中）。

    实际上由于 ssh_session yield 后还在主线程，需要用 asyncio.to_thread 包装。

    Args:
        conn: netmiko 连接对象
        command: 要执行的命令
        netmiko_device_type: netmiko 设备类型字符串

    Returns:
        命令输出文本
    """
    return _send_command(conn, command, netmiko_device_type)


def execute_multi_on_connection(
    conn, commands: list[str], netmiko_device_type: str
) -> list[dict]:
    """在已有连接上顺序执行多条命令。

    单条命令异常不中断，继续执行后续命令。

    Args:
        conn: netmiko 连接对象
        commands: 命令列表
        netmiko_device_type: netmiko 设备类型字符串

    Returns:
        每条命令的结果列表
    """
    results = []
    for cmd in commands:
        try:
            output = _send_command(conn, cmd, netmiko_device_type)
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


# ── 高层接口（向后兼容）────────────────────────────────────────


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
    async with ssh_session(
        host=host, port=port, device_type=device_type,
        username=username, password=password,
    ) as (conn, netmiko_type):
        output = await asyncio.to_thread(_send_command, conn, command, netmiko_type)
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
    async with ssh_session(
        host=host, port=port, device_type=device_type,
        username=username, password=password,
    ) as (conn, netmiko_type):
        results = await asyncio.to_thread(
            execute_multi_on_connection, conn, commands, netmiko_type
        )
    return results


# ── 内部辅助函数 ─────────────────────────────────────────────


def _send_command(conn, command: str, device_type: str) -> str:
    """根据设备类型选择合适的命令发送方式。

    hp_comware / huawei_vrp 使用 send_command_timing（基于时间判断输出结束），
    避免 prompt 误判导致输出截断或串流。
    其他设备使用 send_command（基于 prompt 匹配，更精确）。
    """
    if device_type in _TIMING_DEVICE_TYPES:
        return conn.send_command_timing(command, delay_factor=2)
    return conn.send_command(command, read_timeout=SSH_TIMEOUT)


def _connect_blocking(device_params: dict):
    """同步建立 SSH 连接（在线程中运行）。"""
    return ConnectHandler(**device_params)
