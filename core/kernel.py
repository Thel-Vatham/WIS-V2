import os
import psutil
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class WISKernel:
    """
    Abstracción de Kernel para Swarm OS.
    Expone primitivas de bajo nivel para Procesos, Memoria, Archivos y Diagnóstico.
    """

    def __init__(self, pipeline: Any):
        self.pipeline = pipeline  # Referencia al ActionPipeline

    # --- 1. PROCESOS ---
    
    def process_list(self) -> str:
        """Devuelve un top-like summary de los procesos más pesados."""
        try:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    info = p.info
                    procs.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu": info['cpu_percent'],
                        "mem_mb": info['memory_info'].rss / (1024 * 1024) if info.get('memory_info') else 0
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            # Sort by memory usage descending
            procs = sorted(procs, key=lambda x: x['mem_mb'], reverse=True)[:10]
            
            res = "Top 10 Processes (By Memory):\n"
            for p in procs:
                res += f"PID: {p['pid']} | {p['name']} | CPU: {p['cpu']}% | Mem: {p['mem_mb']:.1f} MB\n"
            return res
        except Exception as e:
            return f"Kernel Error fetching processes: {e}"

    def process_kill(self, pid: str) -> str:
        """Mata forzosamente un proceso."""
        try:
            pid_int = int(pid)
            p = psutil.Process(pid_int)
            name = p.name()
            p.kill()
            return f"SIGKILL sent to PID {pid_int} ({name})."
        except ValueError:
            return "Invalid PID format."
        except psutil.NoSuchProcess:
            return f"PID {pid} not found."
        except psutil.AccessDenied:
            return f"Access Denied to kill PID {pid}."
        except Exception as e:
            return f"Kernel Error killing process: {e}"

    # --- 2. MEMORIA ---
    
    def memory_map(self, session_id: str) -> str:
        """Muestra el uso de la memoria transitoria y persistente."""
        try:
            res = "=== WIS KERNEL MEMORY MAP ===\n\n"
            
            # Memoria Persistente (Chat History)
            mem = self.pipeline.reasoning.memory
            hist = mem.get_history(session_id)
            res += f"[Persistent History]\nMessages: {len(hist)}\n"
            for m in hist:
                role = m.get("role", "unknown")
                content = str(m.get("content", ""))
                res += f" - {role.upper()}: {len(content)} chars\n"
                
            # Memoria Transitoria (Context)
            res += "\n[Transient Context]\n"
            focused = getattr(self.pipeline, "_focused_contexts", {}).get(session_id, {})
            if not focused:
                res += " - (Empty)\n"
            for fname, content in focused.items():
                res += f" - {fname}: {len(content)} chars\n"
                
            return res
        except Exception as e:
            return f"Kernel Error mapping memory: {e}"

    # --- 3. FILESYSTEM ---
    
    def undo_last(self, session_id: str) -> str:
        """Revierte el último cambio si se usa rollback o git."""
        # TODO: Integrate with rollback.py
        return "Kernel Feature '/undo' is hooked but requires Rollback Engine integration (Coming in Phase 2)."

    # --- 4. DEBUGGING ---
    
    def why_last_action(self, session_id: str) -> str:
        """Justificación operacional."""
        trace = getattr(self.pipeline, "_last_trace", {}).get(session_id, [])
        if not trace:
            return "No previous action trace found in memory for this session."
        
        last_step = trace[-1] if trace else {}
        call = last_step.get("call", {})
        note = last_step.get("verification_note", "")
        return f"Operational Justification for last action:\nTool Invoked: {call.get('action')}\nParameters: {call.get('params')}\nVerification: {note}"

    def trace_execution(self, session_id: str) -> str:
        """Debugger agentivo."""
        trace = getattr(self.pipeline, "_last_trace", {}).get(session_id, [])
        if not trace:
            return "No trace available for the last execution."
        
        return json.dumps(trace, indent=2)
