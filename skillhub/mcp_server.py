"""SKILLHUB MCP server - exposes registry listing as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from skillhub.core import Registry, SkillError


def _registry_to_json(registry_path: str) -> str:
    """Scan a registry path and return JSON-serialized skill list."""
    try:
        reg = Registry(registry_path)
        skills = reg.skills()
    except SkillError as exc:
        return json.dumps({"error": str(exc)}, indent=2)
    rows = [s.to_dict() for s in sorted(skills.values(), key=lambda s: s.name)]
    return json.dumps(rows, indent=2, sort_keys=True)


def serve() -> int:
    """Start an MCP stdio server. Requires the optional mcp extra:
        pip install "cognis-skillhub[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install cognis-skillhub[mcp]")
        return 1
    app = FastMCP("skillhub")

    @app.tool()
    def skillhub_scan(registry_path: str = ".") -> str:
        """List skills in a local registry. Returns JSON array of skill metadata."""
        return _registry_to_json(registry_path)

    app.run()
    return 0
