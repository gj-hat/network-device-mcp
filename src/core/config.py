"""
 @author：     JiaGuo
 @emil：       1520047927@qq.com
 @date：       Created in 2025/4/25 10:00
 @description： 全局配置模块，集中管理超时、并发上限、监听地址、设备类型映射等常量
 @modified By：
 @version:     1.0
"""

import os
from pathlib import Path

import yaml

# ── 项目路径 ──────────────────────────────────────────────
# 项目根目录（src/core/ 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 命令配置文件路径
COMMANDS_YAML_PATH = PROJECT_ROOT / "config" / "commands.yaml"

# 全局设置文件路径
SETTINGS_YAML_PATH = PROJECT_ROOT / "config" / "settings.yaml"

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

# ── 健康检测配置（从 settings.yaml 加载）────────────────────
def _load_settings() -> dict:
    """加载 config/settings.yaml，文件不存在时返回空字典。"""
    if SETTINGS_YAML_PATH.exists():
        with open(SETTINGS_YAML_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_settings = _load_settings()
_health_cfg = _settings.get("health_check", {})

HEALTH_CHECK_ENABLED: bool = _health_cfg.get("enabled", True)
HEALTH_CHECK_CPU_THRESHOLD: int = int(_health_cfg.get("cpu_threshold", 80))
HEALTH_CHECK_USER_CHECK_ENABLED: bool = _health_cfg.get("user_check_enabled", False)
HEALTH_CHECK_USER_THRESHOLD: int = int(_health_cfg.get("user_threshold", 4))
HEALTH_CHECK_CPU_CMD_ID: str = _health_cfg.get("cpu_command_id", "_health_cpu")
HEALTH_CHECK_USERS_CMD_ID: str = _health_cfg.get("users_command_id", "_health_users")

