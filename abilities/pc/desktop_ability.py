"""
WIS Desktop Ability.
Wraps AVRORA's window management, process control, and app launching into a WIS Ability.
"""
from __future__ import annotations

from typing import Any
from abilities.base import Ability

from .process import ProcessOps
from .window_tools import WindowOps
from .apps import AppOps

class DesktopAbility(Ability):
    def __init__(self):
        self.process = ProcessOps()
        self.window = WindowOps()
        self.app = AppOps()

    @property
    def name(self) -> str:
        return "desktop"

    @property
    def description(self) -> str:
        return "Manage desktop windows, open applications, and control OS processes."

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "list_windows",
                "description": "List all visible windows.",
                "params": {}
            },
            {
                "action": "focus_window",
                "description": "Bring a window to foreground by its title.",
                "params": {"title": "Title of the window to focus"}
            },
            {
                "action": "list_processes",
                "description": "List running OS processes.",
                "params": {"filter_name": "Optional process name to filter"}
            },
            {
                "action": "kill_process",
                "description": "Terminate a process by name or PID.",
                "params": {"name": "Process name or PID"}
            },
            {
                "action": "open_app",
                "description": "Open an application or file.",
                "params": {"target": "App name, file path, or URL"}
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            if action == "list_windows":
                wins = self.window.list_windows()
                return {"success": True, "data": wins, "message": f"Found {len(wins)} windows"}
                
            elif action == "focus_window":
                title = params.get("title", "")
                success = self.window.focus_window(title)
                return {"success": success, "message": "Window focused" if success else "Window not found"}
                
            elif action == "list_processes":
                procs = self.process.list_processes()
                filter_name = params.get("filter_name")
                if filter_name:
                    procs = [p for p in procs if filter_name.lower() in p["name"].lower()]
                return {"success": True, "data": procs, "message": f"Found {len(procs)} processes"}
                
            elif action == "kill_process":
                name = params.get("name", "")
                killed = self.process.kill_process(name)
                return {"success": bool(killed), "message": f"Killed processes: {killed}" if killed else "Process not found"}
                
            elif action == "open_app":
                target = params.get("target", "")
                self.app.open(target)
                return {"success": True, "message": f"Opened: {target}"}
                
            return {"success": False, "message": f"Unknown action: {action}"}
            
        except Exception as e:
            return {"success": False, "message": str(e)}
