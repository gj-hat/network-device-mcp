#!/usr/bin/env bash
#
# 网络设备只读查询 MCP 服务 — 停止后台服务
# 用法: ./stop.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.mcp.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "[info] 未找到 PID 文件，服务可能未在后台运行"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "[stop] 正在停止服务 (PID: $PID)..."
    kill "$PID"
    # 等待进程退出，最多 10 秒
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    # 如果还没退出，强制 kill
    if kill -0 "$PID" 2>/dev/null; then
        echo "[stop] 进程未响应，强制终止..."
        kill -9 "$PID"
    fi
    echo "[stop] 服务已停止"
else
    echo "[info] 进程 $PID 已不存在"
fi

rm -f "$PID_FILE"
