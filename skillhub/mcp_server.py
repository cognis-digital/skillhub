"""SKILLHUB MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from skillhub.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-skillhub[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-skillhub[mcp]'")
        return 1
    app = FastMCP("skillhub")

    @app.tool()
    def skillhub_scan(target: str) -> str:
        """Local skill registry and installer for AI agents. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
