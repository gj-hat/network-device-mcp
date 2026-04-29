"""凭据管理模块。

从 .env 读取默认 SSH 凭据，支持客户端传入覆盖。
优先级：客户端传入 > 服务端 .env 默认值。
"""

import os

from dotenv import load_dotenv

from src.core.config import DOTENV_PATH

# 启动时加载 .env
load_dotenv(DOTENV_PATH)


class CredentialError(Exception):
    """凭据缺失时抛出的异常。"""


def get_credential(
    username: str | None = None,
    password: str | None = None,
) -> tuple[str, str, str]:
    """获取 SSH 凭据。

    Args:
        username: 客户端传入的用户名（可选）
        password: 客户端传入的密码（可选）

    Returns:
        (username, password, source) 三元组，
        source 为 "client"（客户端传入）或 "default"（服务端默认）

    Raises:
        CredentialError: 无法获取有效凭据时抛出
    """
    # 客户端同时传入了用户名和密码
    if username and password:
        return username, password, "client"

    # 回退到服务端默认凭据
    default_user = os.getenv("SSH_USERNAME")
    default_pass = os.getenv("SSH_PASSWORD")

    if default_user and default_pass:
        return default_user, default_pass, "default"

    raise CredentialError(
        "凭据缺失：客户端未传入 username/password，"
        "且服务端 .env 中未配置 SSH_USERNAME/SSH_PASSWORD"
    )
