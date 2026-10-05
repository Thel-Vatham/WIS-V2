"""
Tests for MCPAbility — wires core/mcp_client.py (MCP stdio) into the registry.
"""
from __future__ import annotations

import pytest

from abilities.mcp import MCPAbility


def test_mcp_schema():
    ab = MCPAbility()
    assert ab.name == "mcp"
    assert ab.domain == "integration"
    actions = [s["action"] for s in ab.get_schema()]
    for expected in ("connect", "disconnect", "list_servers", "list_tools", "call_tool"):
        assert expected in actions


@pytest.mark.asyncio
async def test_mcp_list_servers_empty():
    ab = MCPAbility()
    res = await ab.execute("list_servers", {})
    assert res["success"] is True
    assert res["data"] == []


@pytest.mark.asyncio
async def test_mcp_disconnect_unknown():
    ab = MCPAbility()
    res = await ab.execute("disconnect", {"name": "does_not_exist"})
    assert res["success"] is False


@pytest.mark.asyncio
async def test_mcp_connect_disallowed_command_is_blocked():
    """Security: a binary not in the allowlist must be rejected."""
    ab = MCPAbility()
    res = await ab.execute("connect", {"name": "evil", "command": "totally_not_allowed.exe"})
    assert res["success"] is False
    assert "allowlist" in res["message"].lower() or "security" in res["message"].lower()
