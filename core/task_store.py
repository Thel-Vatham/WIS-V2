"""
WIS Task Store - Persistencia de tareas aisladas en background.
================================================================
Almacena las tareas que están siendo ejecutadas por los Worker Processes.

Tablas:
  - tasks: id, text, status, result, error, created_at, updated_at

Estados de task: executing → done | failed | cancelled
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger("wis.core.task_store")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'executing',
    result      TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


class TaskStore:
    """Persistencia SQLite para tareas asíncronas."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path and str(db_path) != ":memory:":
            self._path = Path(db_path)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connect_target = str(self._path)
        else:
            self._path = None
            connect_target = ":memory:"
            
        self._conn: sqlite3.Connection = sqlite3.connect(
            connect_target, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_db()

    # ---- Conexion ----------------------------------------------------------

    def _init_db(self) -> None:
        with self._lock:
            # Solo para limpieza si venimos del esquema viejo
            try:
                self._conn.execute("DROP TABLE IF EXISTS subtasks")
                self._conn.execute("DROP TABLE IF EXISTS goals")
            except Exception:
                pass
                
            self._conn.executescript(_SCHEMA)
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "session_id" not in columns:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'")
            if "pid" not in columns:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN pid INTEGER")
            if "attempts" not in columns:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ---- Tasks -------------------------------------------------------------

    def create_task(self, text: str, session_id: str = "default") -> dict:
        """Crea una nueva tarea y retorna su representacion."""
        task_id = str(uuid.uuid4())
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id, text, status, created_at, updated_at, session_id) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, text, "executing", now, now, session_id),
            )
            self._conn.commit()
            
        logger.debug("Tarea creada en TaskStore: %s", task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[dict]:
        """Obtiene una tarea por su ID."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_active_tasks(self) -> List[dict]:
        """Devuelve todas las tareas que estan en ejecucion."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tasks WHERE status = 'executing' ORDER BY created_at ASC")
            return [dict(r) for r in cur.fetchall()]

    def get_all_tasks(self, limit: int = 50) -> List[dict]:
        """Devuelve las tareas recientes, activas o finalizadas."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        pid: Optional[int] = None,
        attempts: Optional[int] = None,
    ) -> bool:
        """Actualiza campos de una tarea."""
        now = _utc_now()
        fields = []
        values = []

        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if result is not None:
            fields.append("result = ?")
            values.append(result)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if pid is not None:
            fields.append("pid = ?")
            values.append(pid)
        if attempts is not None:
            fields.append("attempts = ?")
            values.append(attempts)

        if not fields:
            return False

        fields.append("updated_at = ?")
        values.extend([now, task_id])

        query = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
        with self._lock:
            cur = self._conn.execute(query, tuple(values))
            self._conn.commit()
            return cur.rowcount > 0

    def delete_task(self, task_id: str) -> bool:
        """Elimina una tarea completamente."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def clear_all(self) -> None:
        """Limpia todo el TaskStore."""
        with self._lock:
            self._conn.execute("DELETE FROM tasks")
            self._conn.commit()
