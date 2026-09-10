"""TaskManager: background jobs with reactive completion events.

The Brain stays synchronous (question → answer); long tasks run in a
subprocess (shell commands) or a daemon thread (Python callables). When a
job finishes, a ``TASK_COMPLETED`` event is pushed into a queue that the CLI
drains after every reply and re-injects as an automatic turn — the
"reactive wakeup" that lets the agent continue its analysis without the
user typing anything.

Conceptual source: docs 08-reconstruccion (task_manager / event_stream of
the original architecture) rebuilt with the current professional practices.
"""
from __future__ import annotations

import logging
import queue
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


EVENT_TASK_COMPLETED = "TASK_COMPLETED"

# ---------------------------------------------------------------------------
# Safety: blocklist for destructive shell commands (Audit H-04)
# ---------------------------------------------------------------------------
_DESTRUCTIVE_CMD_RE = re.compile(
    r"(?i)(?:"
    r"\bdel\s+/[sfq]"
    r"|\brmdir\s+/s"
    r"|\bformat\s+[a-z]:"
    r"|\brm\s+-r"
    r"|\brd\s+/s"
    r"|\bdiskpart\b"
    r"|\bshutdown\b"
    r"|\breg\s+delete\b"
    r"|\bnet\s+user\b.*\/delete"
    r")"
)


def _validate_command(command: str) -> str | None:
    """Return an error message if the command matches a destructive pattern, else None."""
    if _DESTRUCTIVE_CMD_RE.search(command):
        return "[security] Command blocked by safety policy: contains destructive pattern"
    return None


@dataclass
class BackgroundJob:
    """One background task tracked by the manager."""

    job_id: str
    label: str
    kind: str  # "process" | "thread"
    status: str = "running"  # running | done | failed | killed
    started_at: str = ""
    finished_at: str = ""
    output: str = ""
    error: str = ""
    proc: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    # Progress tracking (reusable, non-static): total may be known (e.g. a web
    # agent's step budget); progress advances as work happens; note is the
    # current activity. The manager computes elapsed / eta / % from these.
    progress: float = 0.0
    total: float | None = None
    unit: str = "steps"
    note: str = ""
    started_ts: float = field(default_factory=time.time)
    finished_ts: float = 0.0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clip(text: str | None, limit: int = 2000) -> str:
    text = text or ""
    return text[:limit] + ("…" if len(text) > limit else "")


def _fmt_seconds(seconds: float) -> str:
    """Human-readable duration: "3m 12s", "45s", "2h 5m"."""
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m"
    if seconds >= 60:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s"
    return f"{seconds}s"


class TaskManager:
    """Launches background jobs and emits completion events."""

    def __init__(self, event_queue: queue.Queue | None = None) -> None:
        self._jobs: dict[str, BackgroundJob] = {}
        self._lock = threading.RLock()
        self.events: queue.Queue = event_queue or queue.Queue()

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------
    def submit_command(self, command: str, label: str | None = None, cwd: str | None = None) -> str:
        """Run a shell command in the background. Returns the ``job_id``.

        The caller (LLM tool) gets the id immediately; completion arrives
        later through :meth:`drain_events`.
        """
        # Safety gate: block destructive patterns just in case
        blocked = _validate_command(command)
        if blocked:
            job = self._new_job(label or command, "process")
            return self._fail_immediately(job, blocked)
        job = self._new_job(label or command, "process")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                cwd=cwd,
                creationflags=creationflags,
            )
        except Exception as exc:  # noqa: BLE001 — spawn failure must be honest
            return self._fail_immediately(job, str(exc))
        job.proc = proc
        watcher = threading.Thread(
            target=self._watch_process, args=(job,), name=f"job-{job.job_id}", daemon=True
        )
        job.thread = watcher
        watcher.start()
        return job.job_id

    def submit_callable(self, fn: Callable[[], str], label: str) -> str:
        """Run a Python callable in a background thread. Returns the ``job_id``."""
        job = self._new_job(label, "thread")
        worker = threading.Thread(
            target=self._run_callable, args=(job, fn), name=f"job-{job.job_id}", daemon=True
        )
        job.thread = worker
        worker.start()
        return job.job_id

    # ------------------------------------------------------------------
    # Status / control
    # ------------------------------------------------------------------
    def status(self, job_id: str) -> dict[str, Any]:
        """Snapshot of a job (safe for the LLM to read)."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"job_id": job_id, "status": "unknown"}
        return {
            "job_id": job.job_id,
            "label": job.label,
            "kind": job.kind,
            "status": job.status,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "output": _clip(job.output),
            "error": job.error,
        }

    def kill(self, job_id: str) -> bool:
        """Terminate a running job and its entire child process tree. Returns False when it cannot be killed."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.status != "running":
            return False
        if job.proc is not None and job.proc.poll() is None:
            try:
                import psutil

                parent = psutil.Process(job.proc.pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.kill()
                    except Exception as _exc:
                        logger.debug("Operacion no fatal suprimida: %s", _exc)
                parent.kill()
            except Exception:
                try:
                    job.proc.kill()
                except OSError:
                    pass
        job.status = "killed"
        job.finished_at = _now()
        job.finished_ts = time.time()
        self._emit(job)
        return True

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._jobs)
        return [self.status(job_id) for job_id in ids]

    # ------------------------------------------------------------------
    # Progress (reusable: callers report "I did X of Y" → dashboard shows %/eta)
    # ------------------------------------------------------------------
    def update_progress(self, job_id: str, progress: float, total: float | None = None, note: str = "") -> None:
        """Advance a job's progress (e.g. web agent step 3/10). Tolerant."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return
        job.progress = float(progress)
        if total is not None:
            job.total = float(total)
        if note:
            job.note = note

    def snapshot(self) -> list[dict[str, Any]]:
        """Enriched view of every job: elapsed, eta, % (for dashboards/LLM).

        Pure and reusable: the CLI renders it, the Brain can inject it, tests
        assert on it. No side effects.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        return [self._snapshot_one(job) for job in jobs]

    def _snapshot_one(self, job: BackgroundJob) -> dict[str, Any]:
        now = time.time()
        elapsed = (job.finished_ts or now) - job.started_ts if job.started_ts else 0.0
        percent: float | None = None
        eta_s: float | None = None
        if job.total and job.total > 0:
            percent = min(100.0, job.progress / job.total * 100.0)
            if job.progress > 0 and job.status == "running":
                rate = job.progress / max(elapsed, 1e-6)
                eta_s = (job.total - job.progress) / rate if rate > 0 else None
        return {
            "job_id": job.job_id,
            "label": job.label,
            "kind": job.kind,
            "status": job.status,
            "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta_s, 1) if eta_s is not None else None,
            "percent": round(percent, 1) if percent is not None else None,
            "progress": job.progress,
            "total": job.total,
            "unit": job.unit,
            "note": job.note,
            "output": _clip(job.output),
            "error": job.error,
        }

    def summary(self) -> str:
        """Plain-text dashboard (for status / LLM context). Reusable."""
        snaps = self.snapshot()
        if not snaps:
            return "no background tasks"
        running = [s for s in snaps if s["status"] == "running"]
        lines = [f"{len(snaps)} task(s) total, {len(running)} running"]
        for s in snaps:
            line = f"- {s['job_id']} [{s['status']}] {s['label']} · elapsed {_fmt_seconds(s['elapsed_s'])}"
            if s["percent"] is not None:
                line += f" · {s['percent']:.0f}%"
                if s["eta_s"] is not None:
                    line += f" · eta {_fmt_seconds(s['eta_s'])}"
            if s["note"]:
                line += f" · {s['note']}"
            lines.append(line)
        return "\n".join(lines)

    def prune_completed_jobs(self, max_retained: int = 100, max_age_seconds: float = 86400.0) -> int:
        """Prune old finished jobs from memory to ensure bounded resource usage indefinitely."""
        now = time.time()
        pruned_count = 0
        with self._lock:
            completed_keys = [
                jid for jid, job in self._jobs.items()
                if job.status in ("done", "failed", "killed")
            ]
            # 1. Prune by age (> 24h)
            for jid in completed_keys:
                job = self._jobs[jid]
                if job.finished_ts and (now - job.finished_ts > max_age_seconds):
                    del self._jobs[jid]
                    pruned_count += 1

            # 2. Prune by count if exceeding max_retained (keep newest)
            remaining_completed = [
                (jid, self._jobs[jid].finished_ts or 0.0)
                for jid in list(self._jobs.keys())
                if self._jobs[jid].status in ("done", "failed", "killed")
            ]
            if len(remaining_completed) > max_retained:
                # Sort by finished_ts ascending (oldest first)
                remaining_completed.sort(key=lambda x: x[1])
                excess = len(remaining_completed) - max_retained
                for jid, _ in remaining_completed[:excess]:
                    if jid in self._jobs:
                        del self._jobs[jid]
                        pruned_count += 1

        return pruned_count

    # ------------------------------------------------------------------
    # Reactive wakeup
    # ------------------------------------------------------------------
    def drain_events(self) -> list[dict[str, Any]]:
        """Non-blocking drain of completed-job events with automatic memory pruning."""
        self.prune_completed_jobs()
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _new_job(self, label: str, kind: str) -> BackgroundJob:
        job = BackgroundJob(job_id=uuid.uuid4().hex[:8], label=label, kind=kind, started_at=_now())
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def _fail_immediately(self, job: BackgroundJob, error: str) -> str:
        job.status = "failed"
        job.error = _clip(error, 500)
        job.finished_at = _now()
        job.finished_ts = time.time()
        self._emit(job)
        return job.job_id

    def _watch_process(self, job: BackgroundJob) -> None:
        assert job.proc is not None
        try:
            output, _ = job.proc.communicate()
            job.output = _clip(output or "")
            job.status = "done" if job.proc.returncode == 0 else "failed"
            if job.status == "failed":
                job.error = _clip(f"exit {job.proc.returncode}", 500)
        except Exception as exc:  # noqa: BLE001 — capture, never crash the thread
            job.status = "failed"
            job.error = _clip(str(exc), 500)
        job.finished_at = _now()
        job.finished_ts = time.time()
        self._emit(job)

    def _run_callable(self, job: BackgroundJob, fn: Callable[[], str]) -> None:
        try:
            job.output = _clip(fn())
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — the job failed, not us
            job.status = "failed"
            job.error = _clip(str(exc), 500)
        job.finished_at = _now()
        job.finished_ts = time.time()
        self._emit(job)

    def _emit(self, job: BackgroundJob) -> None:
        self.events.put(
            {
                "type": EVENT_TASK_COMPLETED,
                "job_id": job.job_id,
                "label": job.label,
                "status": job.status,
                "output": _clip(job.output),
                "error": job.error,
            }
        )
