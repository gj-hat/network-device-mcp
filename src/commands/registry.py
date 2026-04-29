"""命令配置加载与解析模块。

从 config/commands.yaml 加载命令定义，提供：
- 按设备类型查询可用命令列表
- 校验 command_id 和参数
- 拼装最终命令字符串
"""

import ipaddress
import re
from typing import Any

import yaml

from src.core.config import COMMANDS_YAML_PATH, SUPPORTED_DEVICE_TYPES
from src.security.validator import SecurityError, check_blacklist, check_injection

# ── 类型定义（兼容 Python 3.10+）──────────────────────────
ParamDef = dict[str, Any]
CommandDef = dict[str, Any]

# ── 命令注册表（启动时加载一次）─────────────────────────
_registry: dict[str, list[CommandDef]] = {}


def load_commands() -> None:
    """从 YAML 文件加载命令配置到内存。

    应在服务启动时调用一次。
    """
    global _registry
    with open(COMMANDS_YAML_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _registry = {}
    for device_type, commands in raw.items():
        if device_type not in SUPPORTED_DEVICE_TYPES:
            continue
        _registry[device_type] = commands or []


def get_commands(device_type: str = "cisco") -> list[dict[str, Any]]:
    """获取指定设备类型的命令列表（供 list_available_commands 工具）。

    Args:
        device_type: 设备类型

    Returns:
        命令列表，每条包含 command_id, name, description, params
    """
    _ensure_loaded()

    if device_type not in SUPPORTED_DEVICE_TYPES:
        raise ValueError(f"不支持的设备类型: {device_type}，支持: {', '.join(sorted(SUPPORTED_DEVICE_TYPES))}")

    commands = _registry.get(device_type, [])
    result = []
    for cmd in commands:
        result.append({
            "command_id": cmd["id"],
            "name": cmd["name"],
            "description": cmd["description"],
            "params": [
                {
                    "name": p["name"],
                    "type": p["type"],
                    "required": "{" + p["name"] + "}" in cmd.get("command", ""),
                    "description": p.get("description", ""),
                }
                for p in cmd.get("params", [])
            ],
        })
    return result


def resolve_and_validate(
    device_type: str,
    command_id: str,
    params: dict[str, Any] | None = None,
) -> str:
    """校验参数并拼装最终命令。

    流程：
    1. 查找 command_id → 找不到则拒绝
    2. 校验参数（必填、类型、范围、注入）
    3. 拼装最终命令
    4. 兜底黑名单检查

    Args:
        device_type: 设备类型
        command_id: 命令标识
        params: 命令参数 key-value

    Returns:
        拼装后的最终命令字符串

    Raises:
        SecurityError: 安全校验失败
        ValueError: 参数不合法
    """
    _ensure_loaded()
    params = params or {}

    if device_type not in SUPPORTED_DEVICE_TYPES:
        raise ValueError(f"不支持的设备类型: {device_type}")

    # ① 查找命令定义
    cmd_def = _find_command(device_type, command_id)
    if cmd_def is None:
        raise SecurityError(f"未知命令: device_type={device_type}, command_id={command_id}")

    base_command: str = cmd_def["command"]
    param_defs: list[ParamDef] = cmd_def.get("params", [])

    # ② 校验参数并收集替换值
    replacements: dict[str, str] = {}
    for pdef in param_defs:
        pname = pdef["name"]
        value = params.get(pname)

        if value is None:
            # 命令模板中有占位符 {pname} 则参数为必填
            placeholder = "{" + pname + "}"
            if placeholder in base_command:
                raise ValueError(f"缺少必填参数: {pname}")
            continue

        # 转为字符串并校验注入
        str_value = str(value)
        check_injection(str_value)

        # 类型校验
        _validate_type(pdef, str_value)

        replacements[pname] = str_value

    # ③ 拼装命令：替换占位符
    final_command = base_command
    for pname, pvalue in replacements.items():
        final_command = final_command.replace("{" + pname + "}", pvalue)

    # ④ 兜底黑名单
    check_blacklist(final_command)

    return final_command


# ── 内部辅助函数 ─────────────────────────────────────────

def _ensure_loaded() -> None:
    """确保命令配置已加载。"""
    if not _registry:
        load_commands()


def _find_command(device_type: str, command_id: str) -> CommandDef | None:
    """在指定设备类型下查找命令定义。"""
    for cmd in _registry.get(device_type, []):
        if cmd["id"] == command_id:
            return cmd
    return None


def _validate_type(pdef: ParamDef, value: str) -> None:
    """校验参数值是否符合类型定义。

    Raises:
        ValueError: 类型不匹配
    """
    ptype = pdef["type"]
    pname = pdef["name"]

    match ptype:
        case "ip_address":
            try:
                ipaddress.IPv4Address(value)
            except ipaddress.AddressValueError:
                raise ValueError(f"参数 {pname} 不是合法的 IPv4 地址: {value}")

        case "string":
            pattern = pdef.get("pattern")
            if pattern and not re.match(pattern, value):
                raise ValueError(
                    f"参数 {pname} 不符合格式要求（pattern: {pattern}）: {value}"
                )

        case "integer":
            try:
                int_val = int(value)
            except ValueError:
                raise ValueError(f"参数 {pname} 不是合法整数: {value}")

            low = pdef.get("min")
            high = pdef.get("max")
            if low is not None and int_val < low:
                raise ValueError(
                    f"参数 {pname} 小于最小值 {low}: {int_val}"
                )
            if high is not None and int_val > high:
                raise ValueError(
                    f"参数 {pname} 大于最大值 {high}: {int_val}"
                )

        case _:
            raise ValueError(f"未知的参数类型: {ptype}")
