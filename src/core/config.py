"""全局配置模块。

集中管理超时、并发上限、监听地址、设备类型映射等常量。
支持通过环境变量覆盖部分配置。
"""

import os
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────────
# 项目根目录（src/core/ 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 命令配置文件路径
COMMANDS_YAML_PATH = PROJECT_ROOT / "config" / "commands.yaml"

# 审计日志路径
AUDIT_LOG_PATH = PROJECT_ROOT / "logs" / "audit.log"

# .env 文件路径
DOTENV_PATH = PROJECT_ROOT / ".env"

# ── SSH 配置 ──────────────────────────────────────────────
SSH_TIMEOUT: int = int(os.getenv("SSH_TIMEOUT", "30"))

# 批量查询最大并发连接数
MAX_CONCURRENCY: int = int(os.getenv("MAX_CONCURRENCY", "50"))

# ── MCP 服务监听 ─────────────────────────────────────────
HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
PORT: int = int(os.getenv("MCP_PORT", "8081"))

# ── 设备类型映射（本系统 → netmiko device_type）──────────
DEVICE_TYPE_MAP: dict[str, str] = {
    "cisco": "cisco_ios",
    "cisco_asa": "cisco_asa",
    "cisco_nxos": "cisco_nxos",
    "huawei": "huawei_vrp",
    "h3c": "hp_comware",
    "fortinet": "fortinet",
    "aruba": "aruba_os",
    "juniper": "juniper_junos",
    "ruijie": "ruijie_os",
    "ruckus": "ruckus_fastiron",
}

# 支持的设备类型集合（用于快速校验）
SUPPORTED_DEVICE_TYPES: set[str] = set(DEVICE_TYPE_MAP.keys())

# ── 安全相关 ─────────────────────────────────────────────
# 参数值禁止包含的注入字符
INJECTION_CHARS: set[str] = {";", "|", "&", "`", "$", "\n", "\r", "\\"}

# 拼装后命令的兜底危险关键词（全小写匹配）
DANGEROUS_KEYWORDS: list[str] = [
    "configure ", "config t", "config term",
    "config system", "config firewall", "config vpn",
    "system-view",
    "delete", "write ", "erase",
    "reboot", "reload", "shutdown", "format", "destroy",
    "reset", "set ", "clear ", "no ", "copy ", "move ",
    "remove",
]
