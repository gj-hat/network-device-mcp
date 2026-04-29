"""MCP 工具定义模块。

定义 4 个 MCP 工具并注册到 FastMCP 实例：
1. execute_readonly_command — 单设备查询
2. batch_execute_readonly_command — 批量查询
3. list_available_commands — 查看命令菜单
4. execute_multi_commands — 多命令单连接执行（巡检）

本模块是唯一的编排层，协调调用其他所有模块。
"""

import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.commands import registry as command_registry
from src.core import audit
from src.executor import ssh as ssh_executor
from src.executor.ssh import SSHExecutionError
from src.security.credential import CredentialError, get_credential
from src.security.validator import SecurityError


def register_tools(mcp: FastMCP) -> None:
    """将 4 个 MCP 工具注册到 FastMCP 实例。"""

    # ── 工具一：单设备查询 ───────────────────────────────────

    @mcp.tool()
    async def execute_readonly_command(
        host: str,
        command_id: str,
        device_type: str = "cisco",
        params: dict[str, Any] | None = None,
        port: int = 22,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """对指定网络设备执行一条只读命令，返回原始执行结果。

        使用前请先调用 list_available_commands 获取可用的 command_id。

        Args:
            host: 设备 IP 地址
            command_id: 命令标识（从命令菜单获取）
            device_type: 设备类型，支持 cisco / huawei / h3c 等，默认 cisco
            params: 命令参数，key-value 形式（可选）
            port: SSH 端口，默认 22
            username: SSH 用户名（可选，覆盖服务端默认凭据）
            password: SSH 密码（可选，覆盖服务端默认凭据）
        """
        result = await _execute_single(
            tool_name="execute_readonly_command",
            host=host,
            command_id=command_id,
            device_type=device_type,
            params=params,
            port=port,
            username=username,
            password=password,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 工具二：批量查询 ─────────────────────────────────────

    @mcp.tool()
    async def batch_execute_readonly_command(
        hosts: list[str],
        command_id: str,
        device_type: str = "cisco",
        params: dict[str, Any] | None = None,
        port: int = 22,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """对多台设备并发执行同一条只读命令，汇总返回各设备的结果。

        命令校验只做一次，校验失败则所有设备都不执行。
        各设备并发执行，单台失败不影响其他设备。
        并发上限 50 台，超出部分排队等待。

        Args:
            hosts: 设备 IP 地址列表
            command_id: 命令标识
            device_type: 设备类型，默认 cisco
            params: 命令参数（可选）
            port: SSH 端口，默认 22
            username: SSH 用户名（可选）
            password: SSH 密码（可选）
        """
        tool_name = "batch_execute_readonly_command"

        # 命令校验一次
        try:
            final_command = command_registry.resolve_and_validate(
                device_type, command_id, params
            )
        except (SecurityError, ValueError) as e:
            error_msg = str(e)
            audit.log(
                tool=tool_name,
                host=hosts[0] if hosts else "unknown",
                port=port,
                device_type=device_type,
                credential_source="unknown",
                command_id=command_id,
                params=params,
                blocked=isinstance(e, SecurityError),
                block_reason=error_msg if isinstance(e, SecurityError) else "",
                error=error_msg,
            )
            return json.dumps(
                {"success": False, "error": error_msg, "results": []},
                ensure_ascii=False, indent=2,
            )

        # 获取凭据
        try:
            cred_user, cred_pass, cred_source = get_credential(username, password)
        except CredentialError as e:
            return json.dumps(
                {"success": False, "error": str(e), "results": []},
                ensure_ascii=False, indent=2,
            )

        # 并发执行所有设备
        tasks = [
            _execute_on_device(
                tool_name=tool_name,
                host=h,
                port=port,
                device_type=device_type,
                command_id=command_id,
                params=params,
                final_command=final_command,
                username=cred_user,
                password=cred_pass,
                credential_source=cred_source,
            )
            for h in hosts
        ]
        results = await asyncio.gather(*tasks)
        return json.dumps(list(results), ensure_ascii=False, indent=2)

    # ── 工具三：查看命令菜单 ──────────────────────────────────

    @mcp.tool()
    async def list_available_commands(
        device_type: str = "cisco",
    ) -> str:
        """查询指定设备类型可用的命令列表。

        AI 助手应先调用此工具了解可用命令（command_id），
        再使用 execute_readonly_command 或 execute_multi_commands 执行查询。

        Args:
            device_type: 设备类型，支持 cisco / huawei / h3c 等，默认 cisco
        """
        try:
            commands = command_registry.get_commands(device_type)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps(commands, ensure_ascii=False, indent=2)

    # ── 工具四：多命令单连接执行 ──────────────────────────────

    @mcp.tool()
    async def execute_multi_commands(
        commands: list[dict[str, Any]],
        device_type: str = "cisco",
        host: str | None = None,
        hosts: list[str] | None = None,
        port: int = 22,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """对一台或多台设备执行多条只读命令，一次 SSH 连接完成所有命令。

        适用于巡检等需要同时获取多项信息的场景，减少重复建立连接的开销。
        每条命令独立校验，某条校验失败不影响其他命令执行。
        多台设备时各自建立一次连接，设备间并发执行。

        Args:
            commands: 命令列表，每项含 command_id 和可选 params，如
                      [{"command_id": "show_version", "params": {}}, ...]
            device_type: 设备类型，默认 cisco
            host: 单台设备 IP（与 hosts 二选一）
            hosts: 多台设备 IP 列表（与 host 二选一）
            port: SSH 端口，默认 22
            username: SSH 用户名（可选，覆盖服务端默认凭据）
            password: SSH 密码（可选，覆盖服务端默认凭据）
        """
        tool_name = "execute_multi_commands"

        # 参数校验：host 和 hosts 二选一
        target_hosts = _resolve_hosts(host, hosts)
        if not target_hosts:
            return json.dumps(
                {"success": False, "error": "必须提供 host 或 hosts 参数"},
                ensure_ascii=False, indent=2,
            )

        if not commands:
            return json.dumps(
                {"success": False, "error": "commands 不能为空"},
                ensure_ascii=False, indent=2,
            )

        # 获取凭据
        try:
            cred_user, cred_pass, cred_source = get_credential(username, password)
        except CredentialError as e:
            return json.dumps(
                {"success": False, "error": str(e)},
                ensure_ascii=False, indent=2,
            )

        # 逐条校验命令，分离通过/拒绝
        validated_cmds, rejected_results = _validate_commands(
            tool_name=tool_name,
            commands=commands,
            device_type=device_type,
            port=port,
            target_hosts=target_hosts,
        )

        # 并发执行所有目标设备
        tasks = [
            _execute_multi_on_device(
                tool_name=tool_name,
                host=h,
                port=port,
                device_type=device_type,
                username=cred_user,
                password=cred_pass,
                credential_source=cred_source,
                validated_cmds=validated_cmds,
                rejected_results=rejected_results,
            )
            for h in target_hosts
        ]
        all_results = await asyncio.gather(*tasks)

        # 单台设备直接返回对象，多台返回列表
        if len(target_hosts) == 1:
            return json.dumps(all_results[0], ensure_ascii=False, indent=2)
        return json.dumps(list(all_results), ensure_ascii=False, indent=2)


# ── 内部辅助函数 ─────────────────────────────────────────


def _resolve_hosts(
    host: str | None, hosts: list[str] | None
) -> list[str]:
    """解析 host/hosts 参数为统一的列表。"""
    if hosts:
        return hosts
    if host:
        return [host]
    return []


def _validate_commands(
    *,
    tool_name: str,
    commands: list[dict[str, Any]],
    device_type: str,
    port: int,
    target_hosts: list[str],
) -> tuple[list[dict], list[dict]]:
    """逐条校验命令列表。

    Returns:
        (validated_cmds, rejected_results)
        validated_cmds: [{"command_id": str, "params": dict, "final_command": str}, ...]
        rejected_results: [{"command_id": str, "command_executed": "", "success": False, "output": "", "error": str}, ...]
    """
    validated = []
    rejected = []

    for cmd_entry in commands:
        cmd_id = cmd_entry.get("command_id", "")
        cmd_params = cmd_entry.get("params") or {}

        try:
            final_command = command_registry.resolve_and_validate(
                device_type, cmd_id, cmd_params
            )
            validated.append({
                "command_id": cmd_id,
                "params": cmd_params,
                "final_command": final_command,
            })
        except (SecurityError, ValueError) as e:
            error_msg = str(e)
            blocked = isinstance(e, SecurityError)
            # 记录拦截日志（以第一台设备为代表）
            audit.log(
                tool=tool_name,
                host=target_hosts[0] if target_hosts else "unknown",
                port=port,
                device_type=device_type,
                credential_source="unknown",
                command_id=cmd_id,
                params=cmd_params,
                blocked=blocked,
                block_reason=error_msg if blocked else "",
                error=error_msg,
            )
            rejected.append({
                "command_id": cmd_id,
                "command_executed": "",
                "success": False,
                "output": "",
                "error": error_msg,
            })

    return validated, rejected


async def _execute_multi_on_device(
    *,
    tool_name: str,
    host: str,
    port: int,
    device_type: str,
    username: str,
    password: str,
    credential_source: str,
    validated_cmds: list[dict],
    rejected_results: list[dict],
) -> dict[str, Any]:
    """在单台设备上执行多条已校验命令（一次 SSH 连接），并记录审计日志。"""
    results = list(rejected_results)  # 先加入校验失败的命令结果

    if not validated_cmds:
        return {"host": host, "results": results}

    # 提取命令字符串列表
    cmd_strings = [c["final_command"] for c in validated_cmds]

    try:
        ssh_results = await ssh_executor.execute_multi(
            host=host,
            port=port,
            device_type=device_type,
            username=username,
            password=password,
            commands=cmd_strings,
        )

        # 将 SSH 结果与 command_id 对应，逐条记录审计日志
        for cmd_info, ssh_res in zip(validated_cmds, ssh_results):
            audit.log(
                tool=tool_name,
                host=host,
                port=port,
                device_type=device_type,
                credential_source=credential_source,
                command_id=cmd_info["command_id"],
                params=cmd_info["params"],
                command_executed=cmd_info["final_command"],
                success=ssh_res["success"],
                error=ssh_res.get("error", ""),
            )
            results.append({
                "command_id": cmd_info["command_id"],
                "command_executed": cmd_info["final_command"],
                "success": ssh_res["success"],
                "output": ssh_res.get("output", ""),
                "error": ssh_res.get("error", ""),
            })

    except SSHExecutionError as e:
        # 连接建立阶段失败，所有命令都标记失败
        error_msg = str(e)
        for cmd_info in validated_cmds:
            audit.log(
                tool=tool_name,
                host=host,
                port=port,
                device_type=device_type,
                credential_source=credential_source,
                command_id=cmd_info["command_id"],
                params=cmd_info["params"],
                command_executed=cmd_info["final_command"],
                error=error_msg,
            )
            results.append({
                "command_id": cmd_info["command_id"],
                "command_executed": cmd_info["final_command"],
                "success": False,
                "output": "",
                "error": error_msg,
            })

    return {"host": host, "results": results}


async def _execute_single(
    *,
    tool_name: str,
    host: str,
    command_id: str,
    device_type: str,
    params: dict[str, Any] | None,
    port: int,
    username: str | None,
    password: str | None,
) -> dict[str, Any]:
    """单设备执行完整流程：校验 → 凭据 → SSH → 日志。"""
    # ① 命令校验 + 拼装
    try:
        final_command = command_registry.resolve_and_validate(
            device_type, command_id, params
        )
    except (SecurityError, ValueError) as e:
        error_msg = str(e)
        blocked = isinstance(e, SecurityError)
        audit.log(
            tool=tool_name,
            host=host,
            port=port,
            device_type=device_type,
            credential_source="unknown",
            command_id=command_id,
            params=params,
            blocked=blocked,
            block_reason=error_msg if blocked else "",
            error=error_msg if not blocked else "",
        )
        return {
            "host": host,
            "success": False,
            "command_executed": "",
            "output": "",
            "error": error_msg,
        }

    # ② 获取凭据
    try:
        cred_user, cred_pass, cred_source = get_credential(username, password)
    except CredentialError as e:
        audit.log(
            tool=tool_name,
            host=host,
            port=port,
            device_type=device_type,
            credential_source="unknown",
            command_id=command_id,
            params=params,
            command_executed=final_command,
            error=str(e),
        )
        return {
            "host": host,
            "success": False,
            "command_executed": final_command,
            "output": "",
            "error": str(e),
        }

    # ③ SSH 执行
    return await _execute_on_device(
        tool_name=tool_name,
        host=host,
        port=port,
        device_type=device_type,
        command_id=command_id,
        params=params,
        final_command=final_command,
        username=cred_user,
        password=cred_pass,
        credential_source=cred_source,
    )


async def _execute_on_device(
    *,
    tool_name: str,
    host: str,
    port: int,
    device_type: str,
    command_id: str,
    params: dict[str, Any] | None,
    final_command: str,
    username: str,
    password: str,
    credential_source: str,
) -> dict[str, Any]:
    """在单台设备上执行已校验的单条命令并记录日志。"""
    try:
        output = await ssh_executor.execute(
            host=host,
            port=port,
            device_type=device_type,
            username=username,
            password=password,
            command=final_command,
        )
        audit.log(
            tool=tool_name,
            host=host,
            port=port,
            device_type=device_type,
            credential_source=credential_source,
            command_id=command_id,
            params=params,
            command_executed=final_command,
            success=True,
        )
        return {
            "host": host,
            "success": True,
            "command_executed": final_command,
            "output": output,
            "error": "",
        }
    except SSHExecutionError as e:
        audit.log(
            tool=tool_name,
            host=host,
            port=port,
            device_type=device_type,
            credential_source=credential_source,
            command_id=command_id,
            params=params,
            command_executed=final_command,
            error=str(e),
        )
        return {
            "host": host,
            "success": False,
            "command_executed": final_command,
            "output": "",
            "error": str(e),
        }
