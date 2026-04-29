"""安全校验模块。

参数值注入字符检测 — 拦截 Shell 特殊字符。
命令安全性由封闭命令集（commands.yaml）保证，无需兜底黑名单。
"""

from src.core.config import INJECTION_CHARS


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


