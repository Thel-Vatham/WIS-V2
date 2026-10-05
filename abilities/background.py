"""Background Ability — async background jobs for WIS.

Wires the previously orphaned ``core/mission.py`` (TaskManager) into the ability
registry so WIS can launch long-running shell commands or Python callables in
the background and poll their status without blocking the conversation.
"""
from __future__ import annotations

import asyncio
from typing import Any

from abilities.base import Ability
from core.mission import TaskManager


class BackgroundAbility(Ability):
    """Expose the TaskManager (background jobs) as an ability."""

    def __init__(self) -> None:
        self._manager = TaskManager()

    @property
    def name(self) -> str:
        return "background"

    @property
    def description(self) -> str:
        return (
            "Run long tasks in the background (shell commands or Python callables) "
            "and poll their status/kill them without blocking the conversation."
        )

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {"action": "run", "description": "Launch a shell command in the background; returns a job id.", "params": {"command": "shell command", "label": "optional label", "cwd": "optional working dir"}},
            {"action": "status", "description": "Get the status/output of a background job.", "params": {"job_id": "job id"}},
            {"action": "kill", "description": "Kill a running background job.", "params": {"job_id": "job id"}},
            {"action": "list", "description": "List all background jobs.", "params": {}},
            {"action": "summary", "description": "Human-readable summary of all jobs.", "params": {}},
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            a = (action or "").strip().lower()
            p = params or {}

            if a == "run":
                job_id = await asyncio.to_thread(
                    self._manager.submit_command,
                    p.get("command", ""),
                    p.get("label"),
                    p.get("cwd"),
                )
                return {"success": True, "data": {"job_id": job_id}, "message": f"Background job started: {job_id}"}

            if a == "status":
                st = await asyncio.to_thread(self._manager.status, p.get("job_id", ""))
                return {"success": True, "data": st, "message": st.get("status", "unknown")}

            if a == "kill":
                ok = await asyncio.to_thread(self._manager.kill, p.get("job_id", ""))
                return {"success": ok, "message": f"Job '{p.get('job_id')}' killed." if ok else f"Job '{p.get('job_id')}' not killable."}

            if a == "list":
                jobs = await asyncio.to_thread(self._manager.list_jobs)
                return {"success": True, "data": jobs, "message": f"{len(jobs)} job(s)."}

            if a == "summary":
                return {"success": True, "data": self._manager.summary(), "message": "Job summary."}

            return {"success": False, "message": f"Unknown action: {action}"}

        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": f"Background error: {exc}"}
