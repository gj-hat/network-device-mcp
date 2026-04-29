#!/usr/bin/env bash
#
# 网络设备只读查询 MCP 服务 — 启动脚本
# 用法: ./start.sh
#

set -euo pipefail

# 项目根目录（脚本所在位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/src/requirements.txt"

# ── 虚拟环境 ──────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[init] 创建虚拟环境: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# 检查依赖是否已安装（用 pip freeze 快速判断）
if ! pip3 show mcp > /dev/null 2>&1; then
    echo "[init] 安装依赖..."
    pip3 install -r "$REQUIREMENTS"
fi

# ── 目录准备 ──────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/logs"

# ── 启动服务 ──────────────────────────────────────────────
echo "[start] 启动 MCP 服务..."
exec python3 "$SCRIPT_DIR/src/server.py"
