#!/usr/bin/env bash
#
# 网络设备只读查询 MCP 服务 — 前台 Debug 模式启动
# 用法: ./start-debug.sh
# Ctrl+C 停止
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/src/requirements.txt"
PID_FILE="$SCRIPT_DIR/.mcp.pid"

# ── 检查后台实例 ──────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[warn] 后台服务正在运行 (PID: $OLD_PID)，请先执行 ./stop.sh"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# ── 虚拟环境 ──────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[init] 创建虚拟环境: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if ! pip3 show mcp > /dev/null 2>&1; then
    echo "[init] 安装依赖..."
    pip3 install -r "$REQUIREMENTS"
fi

# ── 目录准备 ──────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/logs"

# ── 前台启动（Debug 模式）────────────────────────────────
export MCP_DEBUG=1
echo "[debug] 前台启动 MCP 服务（Ctrl+C 停止）..."
echo "────────────────────────────────────────"
exec python3 "$SCRIPT_DIR/src/server.py"
