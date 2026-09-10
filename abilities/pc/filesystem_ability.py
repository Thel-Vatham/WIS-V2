"""
WIS File System and Shell Abilities.
Wraps AVRORA's core pc operations into standard WIS Abilities.
"""
from __future__ import annotations

import os
from typing import Any
from pathlib import Path

from abilities.base import Ability
from .shell import ShellOps
from .filesystem import FileSystemOps

class ShellAbility(Ability):
    @property
    def name(self) -> str:
        return "shell_comm"

    @property
    def description(self) -> str:
        return "Execute shell commands (Windows PowerShell)."

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "execute_shell",
                "description": "Execute a shell command.",
                "params": {
                    "command": "The command string to execute."
                }
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        if action == "execute_shell":
            cmd = params.get("command")
            if not cmd:
                return {"success": False, "message": "No command provided"}
            try:
                output = ShellOps.run(cmd, timeout=30)
                return {"success": True, "data": output, "message": "Command executed successfully"}
            except Exception as e:
                return {"success": False, "message": str(e)}
        return {"success": False, "message": f"Unknown action: {action}"}

class FileSystemAbility(Ability):
    def __init__(self):
        self.ops = FileSystemOps()

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Read, write, and manage local files and directories."

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "read_file",
                "description": "Read content from a file.",
                "params": {"path": "File path"}
            },
            {
                "action": "write_file",
                "description": "Write or overwrite file content.",
                "params": {"path": "File path", "content": "File content"}
            },
            {
                "action": "list_dir",
                "description": "List directory contents.",
                "params": {"path": "Directory path (optional)"}
            },
            {
                "action": "search",
                "description": "Search for a file by name.",
                "params": {"name": "File or folder name"}
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        path = params.get("path")
        
        if action == "read_file":
            try:
                content = self.ops.read_text(path)
                return {"success": True, "data": content, "message": "File read"}
            except Exception as e:
                return {"success": False, "message": str(e)}
                
        elif action == "write_file":
            try:
                self.ops.write_text(path, params.get("content", ""))
                return {"success": True, "message": f"File written: {path}"}
            except Exception as e:
                return {"success": False, "message": str(e)}
                
        elif action == "list_dir":
            try:
                items = self.ops.list_directory(path)
                return {"success": True, "data": items, "message": "Directory listed"}
            except Exception as e:
                return {"success": False, "message": str(e)}
                
        elif action == "search":
            try:
                name = params.get("name")
                results = self.ops.search(name)
                return {"success": True, "data": [str(p) for p in results], "message": f"Found {len(results)} matches"}
            except Exception as e:
                return {"success": False, "message": str(e)}
                
        return {"success": False, "message": f"Unknown action: {action}"}
