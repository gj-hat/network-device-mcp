"""安全校验模块。

提供两层防护：
1. 参数值注入字符检测 — 拦截 Shell 特殊字符
2. 拼装后命令兜底黑名单 — 防御纵深，防止配置错误导致危险命令通过
"""

from src.core.config import DANGEROUS_KEYWORDS, INJECTION_CHARS


class SecurityError(Exception):
    """安全校验失败时抛出的异常。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def check_injection(value: str) -> None:
    """检查参数值是否包含注入字符。

    Args:
        value: 待检查的参数值（字符串形式）

    Raises:
        SecurityError: 发现注入字符时抛出
    """
    found = INJECTION_CHARS & set(value)
    if found:
        chars_display = ", ".join(repr(c) for c in sorted(found))
        raise SecurityError(f"参数包含非法字符: {chars_display}")


def check_blacklist(command: str) -> None:
    """兜底检查拼装后的最终命令是否包含危险关键词。

    理论上不应触发（因为主命令来自配置文件的安全命令集），
    如果触发说明配置有问题，应立即拒绝并告警。

    Args:
        command: 拼装后的最终命令字符串

    Raises:
        SecurityError: 发现危险关键词时抛出
    """
    cmd_lower = command.lower()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in cmd_lower:
            raise SecurityError(
                f"命令触发兜底安全检查，包含危险关键词: '{keyword.strip()}'"
            )
