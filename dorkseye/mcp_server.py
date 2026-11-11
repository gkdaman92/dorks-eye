"""MCP server: lets any MCP-capable AI client (Claude Desktop/Code, Cursor, VS Code, LM Studio,
Open WebUI, ...) operate Dorks Eye directly.

    dorks-eye mcp                       # stdio (what most desktop clients launch)
    dorks-eye mcp --transport streamable-http
"""

from __future__ import annotations

from typing import Optional

from .ai.tools import TOOLS, ToolExecutor


def _server_class():
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError as e:
        raise SystemExit("[!] Install MCP support: pip install 'dorks-eye[mcp]'  (or pip install mcp)") from e


def build_server(executor: ToolExecutor):
    Server = _server_class()
    server = Server("dorks-eye", instructions=TOOLS[0]["description"])

    @server.tool(name="dork_search", description=TOOLS[0]["description"])
    def dork_search(query: str, engines: Optional[list[str]] = None, max_results: int = 10) -> dict:
        """Run a search dork across engines and return deduplicated results."""
        return executor.dork_search(query, engines, max_results)

    @server.tool(name="list_engines", description=TOOLS[1]["description"])
    def list_engines() -> dict:
        """List available search engines."""
        return executor.list_engines()

    return server


def serve(executor: ToolExecutor, transport: str = "stdio") -> None:
    build_server(executor).run(transport=transport)
