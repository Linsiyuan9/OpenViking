#!/bin/bash
# Start OpenViking MCP Server
# Usage: ./start_mcp.sh [--port 2033] [--transport stdio]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.mcp_server.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "MCP server already running (PID: $OLD_PID). Run stop_mcp.sh first."
        exit 1
    fi
    rm -f "$PID_FILE"
fi

cd "$SCRIPT_DIR"
nohup python3 -m vikingbot.mcp_server "$@" > mcp_server.log 2>&1 &
echo $! > "$PID_FILE"
echo "MCP server started (PID: $!), log: $SCRIPT_DIR/mcp_server.log"
