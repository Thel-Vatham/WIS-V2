"""
WIS Long-Horizon Task Engine.
==============================
Extends GoalManager for tasks that take minutes or hours to complete.

Features:
  - Persistent task state in Data/tasks/<id>/journal.json
  - Daemon mode: tasks continue running when the console is closed and reconnect on open
  - Pause / resume / cancel per-task
  - Real-time event_bus emission for UI consumption
  - Automatic re-planning on subtask failure (semantic retry)
  - Per-subtask configurable timeout (default 5 min)
  - Task diary: full log of every reasoning step, tool call, and result

Lifecycle:
  pending → running → (paused) → done | failed | cancelled

Daemon design:
  A background asyncio event loop runs in its own OS thread.
  WIS main process starts it at boot. The console WebSocket reconnects
  and receives catch-up events since last disconnect.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import event_bus

logger = logging.getLogger("wis.core.long_horizon")

# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_SUBTASK_TIMEOUT = 300   # 5 minutes per subtask
MAX_REPLAN_ATTEMPTS = 2         # semantic re-plan attempts on failure
DAEMON_POLL_INTERVAL = 5.0      # seconds between queue checks


# ── Journal entry structure ────────────────────────────────────────────────────

class JournalEntry:
    """Immutable log entry for a single execution event."""

    def __init__(self, kind: str, data: Any, task_id: str = "") -> None:
        self.ts = datetime.now(timezone.utc).isoformat()
        self.kind = kind
        self.data = data
        self.task_id = task_id

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "task_id": self.task_id,
            "data": self.data,
        }


# ── LongHorizonTask ────────────────────────────────────────────────────────────

class LongHorizonTask:
    """Represents a single long-running task with full persistence."""

    def __init__(
        self,
        task_id: str,
        text: str,
        data_dir: Path,
        priority: int = 5,
        subtask_timeout: float = DEFAULT_SUBTASK_TIMEOUT,
    ) -> None:
        self.id = task_id
        self.text = text
        self.priority = priority
        self.subtask_timeout = subtask_timeout
        self.status: str = "pending"          # pending | running | paused | done | failed | cancelled
        self.plan: List[str] = []             # subtask descriptions
        self.current_step: int = 0
        self.results: List[Dict[str, Any]] = []
        self.replan_attempts: int = 0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.summary: str = ""
        self._journal: List[dict] = []

        # Persistent path
        self._dir = data_dir / "tasks" / task_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._dir / "state.json"
        self._journal_file = self._dir / "journal.jsonl"

        # Control events
        self._pause_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._pause_event.set()  # not paused by default

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        state = {
            "id": self.id,
            "text": self.text,
            "priority": self.priority,
            "status": self.status,
            "plan": self.plan,
            "current_step": self.current_step,
            "results": self.results,
            "replan_attempts": self.replan_attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
        }
        self._state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, task_dir: Path) -> "LongHorizonTask":
        state_file = task_dir / "state.json"
        if not state_file.exists():
            raise FileNotFoundError(f"No state.json in {task_dir}")
        state = json.loads(state_file.read_text(encoding="utf-8"))
        task = cls(
            task_id=state["id"],
            text=state["text"],
            data_dir=task_dir.parent.parent,
            priority=state.get("priority", 5),
        )
        task.status = state.get("status", "pending")
        task.plan = state.get("plan", [])
        task.current_step = state.get("current_step", 0)
        task.results = state.get("results", [])
        task.replan_attempts = state.get("replan_attempts", 0)
        task.created_at = state.get("created_at", task.created_at)
        task.summary = state.get("summary", "")
        return task

    def log(self, kind: str, data: Any) -> None:
        entry = JournalEntry(kind=kind, data=data, task_id=self.id)
        self._journal.append(entry.to_dict())
        try:
            with open(self._journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        # Emit to event_bus for real-time UI
        event_bus.emit(f"long_horizon.{kind}", {"task_id": self.id, **entry.to_dict()})

    def read_journal(self, last_n: int = 50) -> List[dict]:
        if not self._journal_file.exists():
            return []
        lines = self._journal_file.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-last_n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries

    # ── Control API ────────────────────────────────────────────────────────────

    def pause(self) -> None:
        self.status = "paused"
        self._pause_event.clear()
        self.log("paused", {})
        self.save()

    def resume(self) -> None:
        if self.status == "paused":
            self.status = "running"
            self._pause_event.set()
            self.log("resumed", {})
            self.save()

    def cancel(self) -> None:
        self.status = "cancelled"
        self._cancel_event.set()
        self._pause_event.set()  # unblock if paused
        self.log("cancelled", {})
        self.save()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "priority": self.priority,
            "plan": self.plan,
            "current_step": self.current_step,
            "total_steps": len(self.plan),
            "progress_pct": int(self.current_step / len(self.plan) * 100) if self.plan else 0,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
        }


# ── LongHorizonEngine ──────────────────────────────────────────────────────────

class LongHorizonEngine:
    """
    Daemon-mode Long-Horizon Task Engine.

    Runs a dedicated asyncio event loop in a background daemon thread.
    Tasks persist to disk and resume automatically after restart.
    The console WebSocket receives real-time updates via event_bus.
    """

    def __init__(
        self,
        data_dir: Path,
        pipeline: Any,          # ActionPipeline
        llm_client: Any,        # LLMClient
        poll_interval: float = DAEMON_POLL_INTERVAL,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._pipeline = pipeline
        self._llm = llm_client
        self._poll_interval = poll_interval
        self._tasks: Dict[str, LongHorizonTask] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Load persisted tasks
        self._restore_tasks()

    # ── Daemon lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="wis-long-horizon-daemon",
            daemon=True,
        )
        self._thread.start()
        logger.info("LongHorizonEngine daemon started.")

    def stop(self) -> None:
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._daemon_loop())

    async def _daemon_loop(self) -> None:
        logger.info("Long-horizon daemon: entering poll loop.")
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("Long-horizon daemon tick error: %s", exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """One iteration: pick the highest-priority pending/running task and advance it."""
        with self._lock:
            candidates = [
                t for t in self._tasks.values()
                if t.status in ("pending", "running")
            ]
        if not candidates:
            return

        # Sort by priority desc, then created_at asc
        candidates.sort(key=lambda t: (-t.priority, t.created_at))
        task = candidates[0]

        if task.status == "pending":
            await self._plan_task(task)
        elif task.status == "running":
            await self._execute_next_step(task)

    # ── Planning ────────────────────────────────────────────────────────────────

    async def _plan_task(self, task: LongHorizonTask) -> None:
        task.status = "running"
        task.log("planning_start", {"text": task.text})
        task.save()

        plan_prompt = (
            f"You are a task planning expert. Decompose the following long-horizon objective "
            f"into a sequential list of concrete, atomic subtasks (minimum 2, maximum 15).\n"
            f"Each subtask must be a clear instruction that an AI assistant can execute.\n"
            f"Respond ONLY with a JSON object: {{\"steps\": [\"step 1\", \"step 2\", ...]}}\n\n"
            f"OBJECTIVE: {task.text}"
        )

        try:
            response = await asyncio.wait_for(
                self._llm.chat([
                    {"role": "system", "content": "You are a task decomposition expert. Respond only with valid JSON."},
                    {"role": "user", "content": plan_prompt},
                ]),
                timeout=30.0,
            )
            raw = response.get("text", "") if isinstance(response, dict) else str(response)
            # Extract JSON
            import re
            match = re.search(r'\{.*"steps"\s*:\s*\[.*?\]\s*\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                steps = [str(s) for s in parsed.get("steps", []) if str(s).strip()]
                if steps:
                    task.plan = steps
                    task.log("plan_ready", {"steps": steps})
                    task.save()
                    event_bus.emit("long_horizon.plan_ready", {"task_id": task.id, "plan": steps})
                    logger.info("Long-horizon: task '%s' planned (%d steps)", task.id[:8], len(steps))
                    return
        except asyncio.TimeoutError:
            logger.warning("Long-horizon: planning timeout for task %s", task.id[:8])
        except Exception as exc:
            logger.warning("Long-horizon: planning error: %s", exc)

        # Fallback: treat full objective as single step
        task.plan = [task.text]
        task.log("plan_fallback", {"steps": task.plan})
        task.save()

    # ── Execution ───────────────────────────────────────────────────────────────

    async def _execute_next_step(self, task: LongHorizonTask) -> None:
        if task.current_step >= len(task.plan):
            await self._finalize_task(task, success=True)
            return

        # Pause check
        await task._pause_event.wait()
        if task._cancel_event.is_set():
            return

        step_idx = task.current_step
        step_text = task.plan[step_idx]

        task.log("step_start", {"step": step_idx + 1, "text": step_text})
        event_bus.emit("long_horizon.step_start", {
            "task_id": task.id,
            "step": step_idx + 1,
            "total": len(task.plan),
            "text": step_text,
        })

        try:
            result = await asyncio.wait_for(
                self._pipeline.process(step_text),
                timeout=task.subtask_timeout,
            )
            success = result.get("success", False)
            response = result.get("response", "")

            task.results.append({
                "step": step_idx + 1,
                "text": step_text,
                "success": success,
                "response": response,
                "calls": result.get("calls", []),
            })
            task.log("step_done", {"step": step_idx + 1, "success": success, "response": response[:300]})
            event_bus.emit("long_horizon.step_done", {
                "task_id": task.id,
                "step": step_idx + 1,
                "success": success,
                "response": response,
            })

            if success:
                task.current_step += 1
                task.replan_attempts = 0
                task.save()
                # Check if finished
                if task.current_step >= len(task.plan):
                    await self._finalize_task(task, success=True)
            else:
                # Failure: attempt semantic re-plan
                if task.replan_attempts < MAX_REPLAN_ATTEMPTS:
                    task.replan_attempts += 1
                    await self._replan_from_step(task, step_idx, response)
                else:
                    await self._finalize_task(task, success=False, reason=response)

        except asyncio.TimeoutError:
            msg = f"Step {step_idx + 1} timed out after {task.subtask_timeout}s"
            task.log("step_timeout", {"step": step_idx + 1, "timeout": task.subtask_timeout})
            if task.replan_attempts < MAX_REPLAN_ATTEMPTS:
                task.replan_attempts += 1
                await self._replan_from_step(task, step_idx, msg)
            else:
                await self._finalize_task(task, success=False, reason=msg)

        except Exception as exc:
            logger.exception("Long-horizon step execution error: %s", exc)
            task.log("step_error", {"step": step_idx + 1, "error": str(exc)})
            await self._finalize_task(task, success=False, reason=str(exc))

    async def _replan_from_step(self, task: LongHorizonTask, failed_step: int, error: str) -> None:
        """Semantically re-plan the remaining steps given the failure context."""
        completed = task.plan[:failed_step]
        failed = task.plan[failed_step]
        remaining = task.plan[failed_step + 1:]

        replan_prompt = (
            f"ORIGINAL OBJECTIVE: {task.text}\n"
            f"COMPLETED STEPS: {json.dumps(completed)}\n"
            f"FAILED STEP: {failed}\n"
            f"FAILURE REASON: {error}\n"
            f"REMAINING ORIGINAL STEPS: {json.dumps(remaining)}\n\n"
            f"Regenerate the remaining steps (from step {failed_step + 1} onward) to complete the objective, "
            f"accounting for the failure. Use a different approach for the failed step.\n"
            f"Respond ONLY with JSON: {{\"steps\": [\"new step\", ...]}}"
        )

        try:
            response = await asyncio.wait_for(
                self._llm.chat([
                    {"role": "system", "content": "You are a task re-planning expert. Respond only with valid JSON."},
                    {"role": "user", "content": replan_prompt},
                ]),
                timeout=20.0,
            )
            raw = response.get("text", "") if isinstance(response, dict) else str(response)
            import re
            match = re.search(r'\{.*"steps"\s*:\s*\[.*?\]\s*\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                new_steps = [str(s) for s in parsed.get("steps", []) if str(s).strip()]
                if new_steps:
                    task.plan = completed + new_steps
                    task.current_step = len(completed)
                    task.log("replanned", {"from_step": failed_step, "new_steps": new_steps})
                    task.save()
                    event_bus.emit("long_horizon.replanned", {"task_id": task.id, "plan": task.plan})
                    return
        except Exception as exc:
            logger.warning("Long-horizon: replan failed: %s", exc)

        # If replan fails, just skip the failed step and continue
        task.current_step = failed_step + 1
        task.save()

    async def _finalize_task(self, task: LongHorizonTask, success: bool, reason: str = "") -> None:
        task.status = "done" if success else "failed"

        # Generate summary
        try:
            completed = sum(1 for r in task.results if r.get("success"))
            total = len(task.plan)
            responses = [r.get("response", "") for r in task.results[-3:]]
            task.summary = (
                f"{'Completed' if success else 'Failed'} {completed}/{total} subtasks. "
                + " | ".join(r[:100] for r in responses if r)
            )
        except Exception:
            task.summary = "Done" if success else f"Failed: {reason[:100]}"

        task.log("task_done" if success else "task_failed", {
            "success": success,
            "reason": reason,
            "summary": task.summary,
        })
        task.save()

        event_bus.emit("long_horizon.task_complete", {
            "task_id": task.id,
            "success": success,
            "summary": task.summary,
            "reason": reason,
        })
        logger.info("Long-horizon task '%s' finished: success=%s", task.id[:8], success)

    # ── Public API ──────────────────────────────────────────────────────────────

    def create_task(
        self,
        text: str,
        priority: int = 5,
        subtask_timeout: float = DEFAULT_SUBTASK_TIMEOUT,
    ) -> LongHorizonTask:
        task_id = str(uuid.uuid4())
        task = LongHorizonTask(
            task_id=task_id,
            text=text,
            data_dir=self._data_dir,
            priority=priority,
            subtask_timeout=subtask_timeout,
        )
        task.log("created", {"text": text, "priority": priority})
        task.save()
        with self._lock:
            self._tasks[task_id] = task
        event_bus.emit("long_horizon.task_created", task.to_dict())
        logger.info("Long-horizon task created: %s — %s", task_id[:8], text[:60])
        return task

    def get_task(self, task_id: str) -> Optional[LongHorizonTask]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: (-t.priority, t.created_at))
        return [t.to_dict() for t in tasks]

    def pause_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task.pause()
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "paused":
            task.resume()
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in ("pending", "running", "paused"):
            task.cancel()
            return True
        return False

    def get_journal(self, task_id: str, last_n: int = 50) -> List[dict]:
        task = self._tasks.get(task_id)
        if not task:
            return []
        return task.read_journal(last_n=last_n)

    # ── Persistence ─────────────────────────────────────────────────────────────

    def _restore_tasks(self) -> None:
        """Load all persisted tasks from Data/tasks/ on startup."""
        tasks_dir = self._data_dir / "tasks"
        if not tasks_dir.exists():
            return
        for task_dir in tasks_dir.iterdir():
            if not task_dir.is_dir():
                continue
            try:
                task = LongHorizonTask.load(task_dir)
                # Resume pending/running tasks automatically
                if task.status in ("running", "pending"):
                    task.status = "pending"  # force re-entry
                with self._lock:
                    self._tasks[task.id] = task
                logger.info("Long-horizon: restored task %s (%s)", task.id[:8], task.status)
            except Exception as exc:
                logger.debug("Could not restore task from %s: %s", task_dir, exc)
