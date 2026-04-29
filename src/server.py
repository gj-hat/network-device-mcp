"""MCP 服务启动入口。

通过 SSE 传输协议启动 MCP 服务，监听指定地址和端口。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中（支持 python src/server.py 直接运行）
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

from src.commands.registry import load_commands
from src.core.config import HOST, PORT
from src.tools.handlers import register_tools


def create_app() -> FastMCP:
    """创建并配置 MCP 应用实例。"""
    mcp = FastMCP(
        "network-readonly-query",
        host=HOST,
        port=PORT,
    )

    # 预加载命令配置
    load_commands()

    # 注册 3 个 MCP 工具
    register_tools(mcp)

    return mcp


# 全局实例（供 start.sh 或直接运行使用）
app = create_app()

if __name__ == "__main__":
    print(f"启动 MCP 服务: http://{HOST}:{PORT}/sse")
    app.run(transport="sse")
