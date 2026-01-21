"""MCP Server for Slop Food App.

Exposes food app functionality to Claude Code and Claude Chat
via the Model Context Protocol (MCP).
"""

from .server import mcp

__all__ = ["mcp"]
