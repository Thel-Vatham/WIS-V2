"""AVRORA Swarm Coordinator & Multi-Agent Collaboration Engine.

Enables concurrent, non-colliding subagent execution and active inter-agent collaboration:
1. `WorkspaceLockManager`: Fine-grained per-file re-entrant locking to guarantee multiple
   subagents never corrupt or overwrite each other's files.
2. `SwarmBlackboard`: Thread-safe shared bulletin board for inter-agent communication,
   knowledge exchange (OpenAPI specs, architecture plans, schemas), and atomic task claiming.
3. `SwarmCoordinator`: Orchestrator tying locking, blackboard, and subagent telemetry together.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("AVRORA.Swarm")


class SwarmLockConflictError(Exception):
    """Raised when a file lock cannot be acquired because another subagent holds it."""


@dataclass
class SwarmBulletin:
    """A message or artifact published on the shared swarm blackboard."""

    id: str
    topic: str
    sender_id: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkspaceLockManager:
    """Fine-grained file lock manager to prevent concurrent subagents from colliding."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._holders: dict[str, str] = {}  # canonical_path -> agent_id
        self._hold_times: dict[str, float] = {}  # canonical_path -> acquisition timestamp
        self._ref_counts: dict[str, int] = {}  # canonical_path -> reentrant count for same agent

    def _normalize_key(self, path: str | Path) -> str:
        try:
            return str(Path(path).resolve())
        except Exception:
            return str(path)

    def acquire(self, path: str | Path, agent_id: str, timeout: float = 5.0) -> bool:
        """Acquire an exclusive lock on a file for the specified subagent."""
        key = self._normalize_key(path)

        # Enforce security constraint: Never lock or touch .env
        p = Path(key)
        if p.name == ".env" or ".env" in p.parts:
            raise PermissionError("Security Violation: Cannot lock or manipulate .env files.")

        deadline = time.time() + timeout
        with self._cv:
            while True:
                holder = self._holders.get(key)
                if holder is None or holder == agent_id:
                    self._holders[key] = agent_id
                    self._hold_times[key] = time.time()
                    self._ref_counts[key] = self._ref_counts.get(key, 0) + 1
                    logger.debug(
                        f"[SwarmLock] Agent '{agent_id}' acquired lock on '{key}' (count={self._ref_counts[key]})"
                    )
                    return True

                remaining = deadline - time.time()
                if remaining <= 0:
                    logger.warning(
                        f"[SwarmLock] Agent '{agent_id}' timed out acquiring lock on '{key}'. "
                        f"Currently held by '{holder}'."
                    )
                    return False
                self._cv.wait(timeout=min(remaining, 0.05))

    def release(self, path: str | Path, agent_id: str) -> None:
        """Release a held file lock."""
        key = self._normalize_key(path)
        with self._cv:
            if self._holders.get(key) == agent_id:
                count = self._ref_counts.get(key, 1) - 1
                if count <= 0:
                    self._holders.pop(key, None)
                    self._hold_times.pop(key, None)
                    self._ref_counts.pop(key, None)
                    self._cv.notify_all()
                    logger.debug(f"[SwarmLock] Agent '{agent_id}' fully released lock on '{key}'")
                else:
                    self._ref_counts[key] = count
                    logger.debug(f"[SwarmLock] Agent '{agent_id}' decremented lock on '{key}' (count={count})")


    @contextmanager
    def lock_file(
        self,
        path: str | Path,
        agent_id: str,
        timeout: float = 8.0,
    ) -> Generator[None, None, None]:
        """Context manager for acquiring and releasing a file lock cleanly."""
        key = self._normalize_key(path)
        acquired = self.acquire(key, agent_id, timeout=timeout)
        if not acquired:
            holder = self.get_holder(key)
            raise SwarmLockConflictError(
                f"[swarm conflict] File '{Path(key).name}' is currently locked by SubAgent '{holder}'. "
                "Wait or coordinate before editing."
            )
        try:
            yield
        finally:
            self.release(key, agent_id)

    def get_holder(self, path: str | Path) -> str | None:
        key = self._normalize_key(path)
        with self._lock:
            return self._holders.get(key)

    def get_all_locked_files(self) -> dict[str, str]:
        """Return dict of {file_path: agent_id}."""
        with self._lock:
            return dict(self._holders)


class SwarmBlackboard:
    """Thread-safe collaborative blackboard for subagents to exchange information."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bulletins: list[SwarmBulletin] = []
        self._claimed_tasks: dict[str, str] = {}  # task_key -> agent_id
        self._active_agents: dict[str, dict[str, Any]] = {}

    def register_agent(self, agent_id: str, subagent_type: str, objective: str) -> None:
        with self._lock:
            self._active_agents[agent_id] = {
                "agent_id": agent_id,
                "type": subagent_type,
                "objective": objective,
                "status": "running",
                "registered_at": time.time(),
                "last_active": time.time(),
                "current_file": None,
            }

    def unregister_agent(self, agent_id: str, final_status: str = "completed") -> None:
        with self._lock:
            if agent_id in self._active_agents:
                self._active_agents[agent_id]["status"] = final_status
                self._active_agents[agent_id]["last_active"] = time.time()

    def update_agent_status(
        self,
        agent_id: str,
        status: str,
        current_file: str | None = None,
    ) -> None:
        with self._lock:
            if agent_id in self._active_agents:
                self._active_agents[agent_id]["status"] = status
                self._active_agents[agent_id]["last_active"] = time.time()
                if current_file is not None:
                    self._active_agents[agent_id]["current_file"] = current_file

    def post(
        self,
        topic: str,
        message: str,
        sender_id: str | None = None,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SwarmBulletin:
        """Publish a message or data payload to the swarm."""
        sid = sender_id or agent_id or "anonymous"
        bulletin = SwarmBulletin(
            id=uuid.uuid4().hex[:8],
            topic=topic.strip().lower(),
            sender_id=sid,
            message=message.strip(),
            payload=payload or {},
        )
        with self._lock:
            self._bulletins.append(bulletin)
            # Keep blackboard bounded to last 1000 messages
            if len(self._bulletins) > 1000:
                self._bulletins = self._bulletins[-1000:]
        logger.info(f"[SwarmBlackboard] {sender_id} posted on '{topic}': {message[:80]}")
        return bulletin

    def read(
        self,
        topic: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Read recent bulletins, optionally filtered by topic."""
        with self._lock:
            if topic:
                clean_topic = topic.strip().lower()
                matches = [b for b in self._bulletins if b.topic == clean_topic]
            else:
                matches = list(self._bulletins)
            return [b.to_dict() for b in matches[-limit:]]

    def claim_task(self, task_key: str, agent_id: str) -> bool:
        """Atomic claim of a task to ensure two subagents never duplicate work."""
        clean_key = task_key.strip().lower()
        with self._lock:
            if clean_key in self._claimed_tasks:
                return False
            self._claimed_tasks[clean_key] = agent_id
            return True

    def get_task_claimant(self, task_key: str) -> str | None:
        with self._lock:
            return self._claimed_tasks.get(task_key.strip().lower())

    def get_swarm_status(self) -> dict[str, Any]:
        """Return full snapshot of active agents, claims, and recent activity."""
        with self._lock:
            return {
                "active_agents": dict(self._active_agents),
                "claimed_tasks": dict(self._claimed_tasks),
                "total_bulletins": len(self._bulletins),
            }


class SwarmCoordinator:
    """Global coordinator managing locks and collaborative communication."""

    _instance: SwarmCoordinator | None = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self.locks = WorkspaceLockManager()
        self.blackboard = SwarmBlackboard()

    @classmethod
    def get_instance(cls) -> SwarmCoordinator:
        """Singleton access to the shared coordinator across threads and brains."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (primarily for test environments)."""
        with cls._singleton_lock:
            cls._instance = None


class SwarmExecutor:
    """Fan-Out / Fan-In Parallel Subagent Orchestrator.

    Dispatches multiple subagents concurrently respecting host hardware capacity,
    synchronizes their reports, and aggregates results.
    """

    def __init__(self, cfg: Any, max_workers: int | None = None) -> None:
        from .governor import ResourceGovernor

        self.cfg = cfg
        telemetry = ResourceGovernor.get_system_telemetry()
        self.max_workers = max_workers or telemetry["recommended_concurrency"]

    def fan_out_gather(
        self,
        tasks: list[dict[str, Any]],
        timeout: float = 120.0,
    ) -> list[dict[str, Any]]:
        """Dispatch a list of subagent tasks concurrently and gather results.

        tasks format:
        [
            {"task": "Analyze competitor A", "subagent_type": "web"},
            {"task": "Analyze competitor B", "subagent_type": "web"},
            {"task": "Extract financial data", "subagent_type": "research"},
        ]
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from ..web.browser import WebAgent
        from .governor import ResourceGovernor
        from .subagent import SubAgent

        results: list[dict[str, Any]] = [{} for _ in tasks]
        if not tasks:
            return results

        def _run_single(idx: int, t_item: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            sub_type = str(t_item.get("subagent_type", "research"))
            task_text = str(t_item.get("task", "")).strip()
            agent_id = f"swarm-{sub_type}-{uuid.uuid4().hex[:6]}"
            start_t = time.time()

            record: dict[str, Any] = {
                "agent_id": agent_id,
                "subagent_type": sub_type,
                "objective": task_text,
                "status": "pending",
                "result": "",
                "elapsed_seconds": 0.0,
            }

            try:
                if sub_type == "web":
                    web_agent = WebAgent(self.cfg)
                    rep = web_agent.run(task_text, max_steps=getattr(self.cfg, "web_max_steps", 30))
                else:
                    sa = SubAgent(self.cfg, subagent_type=sub_type, agent_id=agent_id)
                    rep = sa.run(task_text)
                record["status"] = "completed"
                record["result"] = rep
            except Exception as exc:  # noqa: BLE001
                record["status"] = "failed"
                record["result"] = f"[subagent error] {exc}"

            record["elapsed_seconds"] = round(time.time() - start_t, 2)
            return idx, record

        # Resource governance: dynamically adjust concurrency under high system pressure
        telemetry = ResourceGovernor.get_system_telemetry()
        if not telemetry.get("can_spawn_code", True) or telemetry.get("cpu_percent", 0.0) >= 85.0:
            logger.warning(
                f"[SwarmGovernor] Throttling concurrency: CPU at {telemetry.get('cpu_percent')}% "
                f"(RAM available: {telemetry.get('ram_available_gb')}GB). Clamping workers to 1."
            )
            workers = 1
        else:
            workers = max(1, min(len(tasks), self.max_workers, telemetry.get("recommended_concurrency", 4)))

        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Usamos ProcessPoolExecutor para paralelismo real multi-nucleo y evitar choques de consola por hilos
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_single, i, t) for i, t in enumerate(tasks)]
            for fut in as_completed(futures, timeout=timeout):
                try:
                    idx, res = fut.result()
                    results[idx] = res
                except Exception as e:
                    logger.error(f"Swarm worker failed: {e}")

        return results

    def run_actor_critic(
        self,
        task: str,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Execute a dual-agent Actor-Critic (Coder + Adversarial Auditor) workflow."""
        from .subagent import SubAgent

        actor_id = f"actor-code-{uuid.uuid4().hex[:6]}"
        auditor_id = f"auditor-critic-{uuid.uuid4().hex[:6]}"

        # Step 1: Actor implements the solution
        actor = SubAgent(self.cfg, subagent_type="code", agent_id=actor_id)
        actor_report = actor.run(task)

        # Step 2: Adversarial Auditor evaluates the implementation
        audit_prompt = (
            f"[Adversarial Code Audit Mission]\n"
            f"Original Objective: {task}\n\n"
            f"Implementation Report from Coder ({actor_id}):\n{actor_report}\n\n"
            "Your sole mission is to be an uncompromising Auditor / Red-Teamer:\n"
            "1. Scrutinize the code for hidden bugs, syntax errors, memory leaks, and unhandled edge cases.\n"
            "2. Verify that no credentials, .env files, or security rules were violated.\n"
            "3. Render a verdict: Start with '[VERDICT: APPROVED]' if the solution is production-grade, "
            "or '[VERDICT: REJECTED]' detailing precisely what must be corrected."
        )
        auditor = SubAgent(self.cfg, subagent_type="research", agent_id=auditor_id)
        auditor_critique = auditor.run(audit_prompt)

        approved = "[VERDICT: APPROVED]" in auditor_critique

        return {
            "task": task,
            "status": "approved" if approved else "rejected",
            "actor_id": actor_id,
            "auditor_id": auditor_id,
            "actor_report": actor_report,
            "auditor_critique": auditor_critique,
            "approved": approved,
        }

