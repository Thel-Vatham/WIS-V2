import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from abilities.base import Ability
from core.event_bus import event_bus

logger = logging.getLogger("wis.abilities.cron")

class CronAbility(Ability):
    """
    Cron Cognitivo para WIS.
    Permite programar tareas autónomas para que WIS las ejecute en background.
    """
    
    def __init__(self):
        self._tasks_file = Path(__file__).parent.parent / "Data" / "cron_tasks.json"
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._cron_loop, daemon=True, name="WIS_Cron")
        self._thread.start()
        
    @property
    def name(self) -> str:
        return "cron"
        
    @property
    def description(self) -> str:
        return "Agenda tareas recurrentes o programadas para el Trabajo Nocturno y autonomía 24/7."
        
    @property
    def domain(self) -> str:
        return "system"
        
    def get_schema(self) -> list:
        return [
            {
                "action": "schedule_task",
                "description": "Agenda una nueva tarea autónoma para que WIS la ejecute repetidamente en background.",
                "params": {
                    "task_id": "string - ID único para la tarea (ej: 'nightly_tests')",
                    "prompt": "string - La instrucción detallada que WIS debe ejecutar cuando despierte",
                    "interval_minutes": "int - Cada cuántos minutos debe ejecutarse (ej: 60)"
                }
            },
            {
                "action": "list_tasks",
                "description": "Muestra todas las tareas programadas.",
                "params": {}
            },
            {
                "action": "remove_task",
                "description": "Elimina una tarea programada.",
                "params": {
                    "task_id": "string - ID de la tarea a borrar"
                }
            }
        ]
        
    def _load_tasks(self) -> dict:
        with self._lock:
            if not self._tasks_file.exists():
                return {}
            try:
                return json.loads(self._tasks_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
                
    def _save_tasks(self, tasks: dict) -> None:
        with self._lock:
            self._tasks_file.parent.mkdir(parents=True, exist_ok=True)
            self._tasks_file.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
            
    def _cron_loop(self):
        """Bucle infinito en background (Daemon) que despierta a WIS."""
        while self._running:
            time.sleep(30) # Revisa cada 30 segundos
            try:
                tasks = self._load_tasks()
                now = time.time()
                modified = False
                for t_id, task in tasks.items():
                    last_run = task.get("last_run", 0)
                    interval = task.get("interval_minutes", 60) * 60
                    if now - last_run >= interval:
                        logger.info(f"Cron trigger disparando: {t_id}")
                        # DESPERTAR A WIS
                        event_bus.emit("pipeline.autonomous_trigger", {
                            "session_id": "cron_daemon", 
                            "prompt": f"[CRON AUTÓNOMO: {t_id}] " + task["prompt"]
                        })
                        task["last_run"] = now
                        modified = True
                
                if modified:
                    self._save_tasks(tasks)
            except Exception as e:
                logger.error(f"Error en bucle Cron: {e}")
                
    async def execute(self, action: str, params: dict) -> dict:
        if action == "schedule_task":
            tid = params.get("task_id")
            prompt = params.get("prompt")
            interval = params.get("interval_minutes", 60)
            if not tid or not prompt:
                return {"success": False, "data": None, "message": "task_id y prompt son obligatorios"}
                
            tasks = self._load_tasks()
            tasks[tid] = {
                "prompt": prompt,
                "interval_minutes": interval,
                "last_run": 0 # Forzar ejecución en el siguiente tick (30s)
            }
            self._save_tasks(tasks)
            return {"success": True, "data": None, "message": f"Tarea '{tid}' agendada. Se ejecutará cada {interval} min."}
            
        elif action == "list_tasks":
            tasks = self._load_tasks()
            return {"success": True, "data": tasks, "message": f"{len(tasks)} tareas activas."}
            
        elif action == "remove_task":
            tid = params.get("task_id")
            tasks = self._load_tasks()
            if tid in tasks:
                del tasks[tid]
                self._save_tasks(tasks)
                return {"success": True, "data": None, "message": f"Tarea {tid} eliminada."}
            return {"success": False, "data": None, "message": "Tarea no encontrada."}
            
        return {"success": False, "data": None, "message": f"Unknown action {action}"}

def setup(registry):
    registry.register(CronAbility())
