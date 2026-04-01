#!/bin/bash
# Stop OpenViking MCP Server

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.mcp_server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Server may not be running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "MCP server stopped (PID: $PID)."
else
    echo "Process python3 $PID not found. Cleaning up."
fi
rm -f "$PID_FILE"
