"""MCP Ability — Model Context Protocol (MCP) integration for WIS.

Wires the previously orphaned ``core/mcp_client.py`` into the ability registry
so WIS can connect to any standard MCP server (GitHub, Filesystem, SQLite,
Postgres, Brave Search, …) over stdio JSON-RPC 2.0.

Security: the underlying client allowlists executable binaries before they are
spawned as child MCP servers.
"""
from __future__ import annotations

import asyncio
from typing import Any

from abilities.base import Ability
from core.mcp_client import MCPManager


class MCPAbility(Ability):
    """Expose MCP server connections and tool calls as a first-class ability."""

    def __init__(self) -> None:
        self._manager = MCPManager()

    @property
    def name(self) -> str:
        return "mcp"

    @property
    def description(self) -> str:
        return (
            "Connect to Model Context Protocol (MCP) servers over stdio and call "
            "their tools (GitHub, Filesystem, SQLite, Postgres, search, etc.)."
        )

    @property
    def domain(self) -> str:
        return "integration"

    def get_schema(self) -> list:
        return [
            {
                "action": "connect",
                "description": "Spawn and connect to an MCP server process (binary must be allowlisted).",
                "params": {"name": "logical server name", "command": "executable path", "args": "optional list of args"},
            },
            {
                "action": "disconnect",
                "description": "Close and unregister an MCP server.",
                "params": {"name": "server name"},
            },
            {
                "action": "list_servers",
                "description": "List active MCP servers and their discovered tools.",
                "params": {},
            },
            {
                "action": "list_tools",
                "description": "List tools across active MCP servers (optionally one server).",
                "params": {"server": "optional server name"},
            },
            {
                "action": "call_tool",
                "description": "Call a tool on an MCP server with JSON arguments.",
                "params": {"server": "server name", "tool": "tool name", "arguments": "JSON object of arguments"},
            },
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            a = (action or "").strip().lower()
            p = params or {}

            if a == "connect":
                args = p.get("args") or []
                if isinstance(args, str):
                    args = [args]
                client = await asyncio.to_thread(
                    self._manager.connect, p.get("name", ""), p.get("command", ""), args
                )
                tools = [t.name for t in client.list_tools()] if client.is_alive() else []
                return {"success": True, "data": {"server": p.get("name"), "tools": tools}, "message": f"Connected to MCP server '{p.get('name')}' ({len(tools)} tools)."}

            if a == "disconnect":
                ok = await asyncio.to_thread(self._manager.disconnect, p.get("name", ""))
                return {"success": ok, "data": ok, "message": f"Disconnected '{p.get('name')}'." if ok else f"Server '{p.get('name')}' not found."}

            if a == "list_servers":
                servers = await asyncio.to_thread(self._manager.list_servers)
                return {"success": True, "data": servers, "message": f"{len(servers)} active MCP server(s)."}

            if a == "list_tools":
                server = p.get("server")
                tools = await asyncio.to_thread(self._manager.get_all_tools)
                if server:
                    tools = [t for t in tools if t.server_name == server]
                data = [{"name": t.name, "description": t.description, "server": t.server_name, "schema": t.input_schema} for t in tools]
                return {"success": True, "data": data, "message": f"{len(data)} tool(s) found."}

            if a == "call_tool":
                server = p.get("server", "")
                tool = p.get("tool", "")
                arguments = p.get("arguments", {})
                if isinstance(arguments, str):
                    import json
                    arguments = json.loads(arguments) if arguments.strip() else {}
                client = self._manager._clients.get(server)
                if client is None:
                    return {"success": False, "message": f"MCP server '{server}' not connected."}
                result = await asyncio.to_thread(client.call_tool, tool, arguments)
                return {"success": True, "data": result, "message": str(result)[:4000]}

            return {"success": False, "message": f"Unknown action: {action}"}

        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": f"MCP error: {exc}"}
