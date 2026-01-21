#!/bin/bash
# MCP Server runner - loads .env and starts the server

cd "$(dirname "$0")/.."

# Load .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set default user ID if not set
export SLOP_DEFAULT_USER_ID="${SLOP_DEFAULT_USER_ID:-b7ddfbbd-58c0-4076-9406-58dd1930aee5}"

# Run the MCP server
exec python3 -m mcp_server.server
