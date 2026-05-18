#!/usr/bin/env bash
#
# 网络设备只读查询 MCP 服务 — 重启
# 用法: ./restart.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[restart] 正在重启 MCP 服务..."

# 停止现有服务（忽略未运行的情况）
"$SCRIPT_DIR/stop.sh" || true

# 启动服务
"$SCRIPT_DIR/start.sh"

echo "[restart] 重启完成"
