"""Model Context Protocol (MCP) Stdio Client.

Enables AVRORA to connect to any standard MCP server (e.g., GitHub, Filesystem,
SQLite, Brave Search, Postgres) via JSON-RPC 2.0 over standard I/O (stdio).

Includes security allowlisting to ensure only verified executable binaries
are launched as child MCP servers.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("AVRORA.MCP")

# Safe allowlist of executable binaries permitted to run as MCP servers
_DEFAULT_MCP_ALLOWLIST = frozenset({
    "npx", "npx.cmd", "node", "node.exe", "python", "python.exe",
    "python3", "python3.exe", "uvx", "uvx.exe", "uv", "uv.exe",
})

_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_.:/-]{1,160}$")


class MCPError(Exception):
    """Base exception for MCP protocol operations."""


class MCPSecurityError(MCPError):
    """Raised when an MCP command violates the security policy."""


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server process."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout_sec: int = 30


@dataclass
class MCPTool:
    """Represents a tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


def _is_command_allowed(command: str) -> bool:
    """Check if the executable binary basename is in the security allowlist."""
    if not command:
        return False
    base = Path(command).name.lower()
    allowed = set(_DEFAULT_MCP_ALLOWLIST)
    env_extra = [
        c.strip().lower()
        for c in os.getenv("AVRORA_MCP_ALLOWLIST", "").split(",")
        if c.strip()
    ]
    allowed.update(env_extra)
    return base in allowed


class MCPClient:
    """Client for managing and communicating with an MCP server via JSON-RPC stdio."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._incoming: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._request_id = 0
        self._lock = threading.Lock()
        self._tools: list[MCPTool] = []
        self._is_initialized = False

    def start(self) -> None:
        """Spawn the MCP server process and initialize the session."""
        if not self.config.command:
            raise MCPError(f"No command specified for MCP server '{self.config.name}'.")

        if not _is_command_allowed(self.config.command):
            raise MCPSecurityError(
                f"Command '{self.config.command}' is not in the MCP security allowlist."
            )

        cmd = [self.config.command, *self.config.args]
        env = os.environ.copy()
        env.update(self.config.env)
        cwd = str(Path(self.config.cwd).resolve()) if self.config.cwd else None

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=flags,
        )

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        self._initialize()

    def _reader_loop(self) -> None:
        """Background thread reading JSON-RPC responses from server stdout."""
        if not self._process or not self._process.stdout:
            return
        for line in self._process.stdout:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                msg = json.loads(line_str)
                if isinstance(msg, dict):
                    self._incoming.put(msg)
            except json.JSONDecodeError:
                logger.debug("Non-JSON stdout from MCP server '%s': %s", self.config.name, line_str)
        self._incoming.put(None)

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and await matching response."""
        if not self._process or not self._process.stdin:
            raise MCPError("MCP server process is not running.")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            self._process.stdin.write(line)
            self._process.stdin.flush()

        # Wait for matching response id
        start_ts = threading.Event()
        timeout = self.config.timeout_sec
        deadline = threading.Timer(timeout, start_ts.set)
        deadline.start()

        try:
            while True:
                try:
                    res = self._incoming.get(timeout=1.0)
                except queue.Empty:
                    if not self.is_alive():
                        raise MCPError(f"MCP server '{self.config.name}' terminated unexpectedly.") from None
                    if start_ts.is_set():
                        raise MCPError(f"MCP request '{method}' timed out after {timeout}s.") from None
                    continue

                if res is None:
                    raise MCPError(f"MCP server '{self.config.name}' closed output stream.")

                if res.get("id") == req_id:
                    deadline.cancel()
                    if "error" in res:
                        err = res["error"]
                        raise MCPError(f"MCP Error ({err.get('code')}): {err.get('message')}")
                    return res.get("result", {})
        finally:
            deadline.cancel()

    def _initialize(self) -> None:
        """Perform MCP initialize handshake and discover available tools."""
        res = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "AVRORA", "version": "2.0.0"},
        })
        self._is_initialized = True
        logger.info("Initialized MCP server '%s': %s", self.config.name, res.get("serverInfo", {}))

        # Send notifications/initialized
        if self._process and self._process.stdin:
            notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            self._process.stdin.write(notif)
            self._process.stdin.flush()

        self.refresh_tools()

    def refresh_tools(self) -> list[MCPTool]:
        """Fetch tools list from the MCP server."""
        res = self._send("tools/list")
        raw_tools = res.get("tools", [])
        tools = []
        for t in raw_tools:
            name = str(t.get("name", "")).strip()
            if not name or not _TOOL_NAME_RE.match(name):
                continue
            tools.append(MCPTool(
                name=name,
                description=str(t.get("description", "")).strip(),
                input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                server_name=self.config.name,
            ))
        self._tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on the MCP server."""
        if not self._is_initialized:
            raise MCPError("MCP client is not initialized.")
        res = self._send("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        content = res.get("content", [])
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "\n".join(parts) if parts else str(res)
        return str(res)

    def list_tools(self) -> list[MCPTool]:
        return list(self._tools)

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        """Terminate the MCP server process gracefully."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception as _exc:
                    logger.debug("Operacion no fatal suprimida: %s", _exc)
            finally:
                self._process = None
                self._is_initialized = False


class MCPManager:
    """Manager for multiple Model Context Protocol (MCP) server connections."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.Lock()

    def connect(self, name: str, command: str, args: list[str] | None = None) -> MCPClient:
        """Spawn and register an MCP server connection."""
        with self._lock:
            if name in self._clients:
                self._clients[name].close()
            cfg = MCPServerConfig(name=name, command=command, args=args or [])
            client = MCPClient(cfg)
            client.start()
            self._clients[name] = client
            return client

    def disconnect(self, name: str) -> bool:
        """Close and unregister an MCP server."""
        with self._lock:
            client = self._clients.pop(name, None)
            if client:
                client.close()
                return True
            return False

    def list_servers(self) -> list[dict[str, Any]]:
        """List active MCP servers and their discovered tools."""
        with self._lock:
            res = []
            for name, client in self._clients.items():
                tools = client.list_tools() if client.is_alive() else []
                res.append({
                    "name": name,
                    "alive": client.is_alive(),
                    "command": client.config.command,
                    "tools_count": len(tools),
                    "tools": [t.name for t in tools],
                })
            return res

    def get_all_tools(self) -> list[MCPTool]:
        """Aggregate all tools across active MCP servers."""
        with self._lock:
            all_tools: list[MCPTool] = []
            for client in self._clients.values():
                if client.is_alive():
                    all_tools.extend(client.list_tools())
            return all_tools

    def close_all(self) -> None:
        """Gracefully disconnect all active MCP servers."""
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()

