"""Swarm Ability — multi-agent coordination primitives for WIS.

Wires the previously orphaned ``core/swarm.py`` (SwarmCoordinator) into the
ability registry. Exposes the functional, self-contained concurrency surface:

- Blackboard messaging (broadcast / inbox / claim_task / status) so multiple
  subagents can coordinate without stepping on each other.
- Fine-grained per-file locks (lock_file / unlock_file / locked_files) so
  concurrent subagents never corrupt each other's edits.
"""
from __future__ import annotations

import asyncio
from typing import Any

from abilities.base import Ability
from core.swarm import SwarmCoordinator


class SwarmAbility(Ability):
    """Expose the SwarmCoordinator (blackboard + file locks) as an ability."""

    def __init__(self) -> None:
        self._coordinator = SwarmCoordinator.get_instance()

    @property
    def name(self) -> str:
        return "swarm"

    @property
    def description(self) -> str:
        return (
            "Multi-agent coordination: shared blackboard messaging, atomic task "
            "claiming, and fine-grained file locks for concurrent subagents."
        )

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {"action": "register_agent", "description": "Register a subagent in the swarm.", "params": {"agent_id": "str", "subagent_type": "str", "objective": "str"}},
            {"action": "broadcast", "description": "Post a message/payload to the shared blackboard.", "params": {"topic": "str", "message": "str", "sender_id": "optional str"}},
            {"action": "inbox", "description": "Read recent blackboard messages, optionally by topic.", "params": {"topic": "optional str", "limit": "int"}},
            {"action": "claim_task", "description": "Atomically claim a task key (prevents duplicate work).", "params": {"task_key": "str", "agent_id": "str"}},
            {"action": "task_claimant", "description": "Get the agent that claimed a task key.", "params": {"task_key": "str"}},
            {"action": "status", "description": "Full swarm snapshot (agents, claims, activity).", "params": {}},
            {"action": "lock_file", "description": "Acquire an exclusive lock on a file for an agent.", "params": {"path": "str", "agent_id": "str"}},
            {"action": "unlock_file", "description": "Release a held file lock.", "params": {"path": "str", "agent_id": "str"}},
            {"action": "locked_files", "description": "List currently locked files and their holders.", "params": {}},
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            a = (action or "").strip().lower()
            p = params or {}
            bb = self._coordinator.blackboard
            locks = self._coordinator.locks

            if a == "register_agent":
                bb.register_agent(p.get("agent_id", "agent"), p.get("subagent_type", "general"), p.get("objective", ""))
                return {"success": True, "message": f"Agent '{p.get('agent_id')}' registered."}

            if a == "broadcast":
                bulletin = bb.post(
                    topic=p.get("topic", "general"),
                    message=p.get("message", ""),
                    sender_id=p.get("sender_id") or p.get("agent_id"),
                )
                return {"success": True, "data": bulletin.to_dict(), "message": f"Posted on '{bulletin.topic}'."}

            if a == "inbox":
                msgs = bb.read(topic=p.get("topic"), limit=int(p.get("limit", 20)))
                return {"success": True, "data": msgs, "message": f"{len(msgs)} message(s)."}

            if a == "claim_task":
                ok = bb.claim_task(p.get("task_key", ""), p.get("agent_id", "agent"))
                return {"success": ok, "message": f"Task '{p.get('task_key')}' claimed." if ok else f"Task '{p.get('task_key')}' already claimed."}

            if a == "task_claimant":
                claimant = bb.get_task_claimant(p.get("task_key", ""))
                return {"success": True, "data": claimant, "message": str(claimant or "unclaimed")}

            if a == "status":
                return {"success": True, "data": bb.get_swarm_status(), "message": "Swarm status snapshot."}

            if a == "lock_file":
                ok = await asyncio.to_thread(locks.acquire, p.get("path", ""), p.get("agent_id", "agent"), 5.0)
                return {"success": ok, "message": f"Lock acquired on '{p.get('path')}'." if ok else f"Lock on '{p.get('path')}' is held by another agent."}

            if a == "unlock_file":
                await asyncio.to_thread(locks.release, p.get("path", ""), p.get("agent_id", "agent"))
                return {"success": True, "message": f"Lock released on '{p.get('path')}'."}

            if a == "locked_files":
                return {"success": True, "data": locks.get_all_locked_files(), "message": "Locked files."}

            return {"success": False, "message": f"Unknown action: {action}"}

        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": f"Swarm error: {exc}"}
