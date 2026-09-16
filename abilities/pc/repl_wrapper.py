import os
import sys
import time
import json
import threading
import subprocess
import tempfile
import queue
from pathlib import Path
from .code_interpreter import _sanitized_env, _creationflags, _kill_process_tree, DEFAULT_TIMEOUT_SECONDS

class PersistentREPL:
    _instance: 'PersistentREPL | None' = None

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.work_dir: tempfile.TemporaryDirectory | None = None
        self.lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        self.work_dir = tempfile.TemporaryDirectory(prefix="avrora_repl_sbx_", ignore_cleanup_errors=True)
        repl_script = Path(__file__).parent / "repl_server.py"
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(repl_script)],
            cwd=self.work_dir.name,
            env=_sanitized_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creationflags(),
            start_new_session=(os.name != "nt"),
        )
        
    def reset(self):
        if self.proc:
            try:
                _kill_process_tree(self.proc)
            except Exception:
                pass
            self.proc = None
        if self.work_dir:
            try:
                self.work_dir.cleanup()
            except Exception:
                pass
            self.work_dir = None
            
    def run_code(self, code: str, timeout: int, cancel_event=None) -> tuple[str, str]:
        with self.lock:
            self.start()
            if not self.proc or not self.proc.stdin or not self.proc.stdout:
                return "", "REPL no pudo iniciar."
            
            req_id = str(time.time())
            req = {"id": req_id, "code": code}
            
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                self.reset()
                return "", f"Error escribiendo al REPL: {e}"
                
            q = queue.Queue()
            
            def _reader():
                try:
                    if self.proc and self.proc.stdout:
                        line = self.proc.stdout.readline()
                        q.put(line)
                except Exception:
                    q.put(None)
                    
            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            
            start_time = time.perf_counter()
            while True:
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    self.reset()
                    return "", "Error: ejecución cancelada (REPL reiniciado, estado perdido)."
                    
                if time.perf_counter() - start_time > timeout:
                    self.reset()
                    return "", f"Error: timeout de {timeout}s excedido. REPL reiniciado."
                    
                try:
                    line = q.get(timeout=0.2)
                    if not line:
                        self.reset()
                        return "", "REPL murió inesperadamente."
                    try:
                        res = json.loads(line)
                        return res.get("stdout", ""), res.get("stderr", "")
                    except Exception as e:
                        return "", f"Error parseando respuesta REPL: {e}"
                except queue.Empty:
                    if self.proc.poll() is not None:
                        self.reset()
                        return "", "REPL process was terminated unexpectedly."
                    continue

