"""审计日志模块。

每次操作（成功、失败、被拦截）写入一条 JSON 行到 logs/audit.log。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.core.config import AUDIT_LOG_PATH

# ── 日志初始化 ────────────────────────────────────────────
_logger = logging.getLogger("audit")
_logger.setLevel(logging.INFO)
_logger.propagate = False

# 确保日志目录存在
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_handler = logging.FileHandler(AUDIT_LOG_PATH, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)


def log(
    *,
    tool: str = "",
    host: str,
    port: int = 22,
    device_type: str,
    credential_source: str,
    command_id: str,
    params: dict[str, Any] | None = None,
    command_executed: str = "",
    success: bool = False,
    error: str = "",
    blocked: bool = False,
    block_reason: str = "",
) -> None:
    """写入一条审计日志。

    Args:
        tool: 来源工具名称（execute_readonly_command / batch_execute_readonly_command / execute_multi_commands）
        host: 目标设备 IP
        port: SSH 端口
        device_type: 设备类型
        credential_source: 凭据来源（"default" 或 "client"）
        command_id: 命令标识
        params: 命令参数
        command_executed: 最终拼装的命令
        success: 执行是否成功
        error: 错误信息
        blocked: 是否被安全校验拦截
        block_reason: 拦截原因
    """
    record = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "tool": tool,
        "host": host,
        "port": port,
        "device_type": device_type,
        "credential_source": credential_source,
        "command_id": command_id,
        "params": params or {},
        "command_executed": command_executed,
        "success": success,
        "error": error,
        "blocked": blocked,
        "block_reason": block_reason,
    }
    _logger.info(json.dumps(record, ensure_ascii=False))
