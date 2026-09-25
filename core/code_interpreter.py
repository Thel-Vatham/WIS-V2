"""Hardened Python Code Interpreter (sandboxed REPL) for AVRORA.

Threat model
------------
The code executed here is **LLM-generated** and may be influenced by untrusted
input (web pages, documents, emails → prompt injection). Running it with the
host interpreter is equivalent to Remote Code Execution, so this module
implements defence-in-depth instead of blind trust:

1. **Static risk assessment** (AST + pattern scan) before execution.
2. **Privilege modes** (``strict`` | ``balanced`` | ``trusted``) deciding which
   risk classes run automatically and which require explicit user confirmation.
3. **Hard deny-list**: catastrophic operations (format/shutdown/diskpart/registry
   wipes…) are never executed, in any mode.
4. **Isolated working directory**: each run gets a throwaway temp dir as CWD.
5. **Sanitized environment**: variables that look like secrets (API keys, tokens,
   passwords…) are stripped from the child environment.
6. **Resource limits**: wall-clock timeout + RSS memory cap.
7. **Full process-tree termination**: on timeout/limit the entire descendant
   tree is killed (job objects / ``taskkill /T`` / ``psutil``), never just the
   direct child.

This is *containment*, not a kernel-level sandbox: for hostile workloads use a
container/VM. It closes the realistic prompt-injection → RCE path for a desktop
agent while keeping legitimate automation usable.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Privilege modes
# ---------------------------------------------------------------------------
MODE_STRICT = "strict"
MODE_BALANCED = "balanced"
MODE_TRUSTED = "trusted"
VALID_MODES = (MODE_STRICT, MODE_BALANCED, MODE_TRUSTED)

# Default resource envelope
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_MEMORY_MB = 1024

# ---------------------------------------------------------------------------
# Risk classes
# ---------------------------------------------------------------------------
RISK_SAFE = "safe"  # pure computation — always allowed
RISK_ELEVATED = "elevated"  # FS writes, network — allowed in balanced/trusted
RISK_DANGEROUS = "dangerous"  # process exec, native API, registry — needs confirm
RISK_DENIED = "denied"  # catastrophic — never executed

# `deny` → always blocked (all modes)
_DENIED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bformat\s+[a-z]:", re.I), "filesystem format"),
    (re.compile(r"(?i)\bdiskpart\b"), "disk partitioning"),
    (re.compile(r"(?i)\bshutdown\s+/[sr]|\bStop-Computer\b"), "system shutdown/restart"),
    (re.compile(r"(?i)\breg\s+delete\b|\bwinreg\.DeleteKey\b"), "registry deletion"),
    (re.compile(r"(?i)\bdel\s+/[sfq]\b|\brmdir\s+/s\b|\brd\s+/s\b|\brm\s+-rf\s+/"), "recursive system deletion"),
    (re.compile(r"(?i)\bvssadmin\s+delete\b|\bcipher\s+/w\b|\bbcdedit\b"), "disk/backup destruction"),
    (re.compile(r"(?i)\bnet\s+user\b[^\n]*/delete"), "account deletion"),
)

# `elevated` → automatic in balanced/trusted, confirmation in strict
_ELEVATED_IMPORTS = frozenset({"socket", "requests", "urllib", "httpx", "ftplib", "smtplib", "telnetlib", "aiohttp"})
_ELEVATED_CALLS = frozenset({"open", "write_text", "write_bytes", "urlopen", "urlretrieve"})

# `dangerous` → confirmation in strict/balanced, automatic in trusted
_DANGEROUS_IMPORTS = frozenset(
    {
        "subprocess", "ctypes", "winreg", "win32api", "win32con", "win32gui", "win32process",
        "pty", "pyautogui", "keyboard",
    }
)
_DANGEROUS_CALLS = frozenset(
    {
        "system", "popen", "execv", "execvp", "spawnv", "spawnl", "run", "call", "check_output", "Popen",
        "rmtree", "remove", "unlink", "rmdir", "removedirs", "kill", "terminate", "startfile", "ShellExecuteW",
        "CreateProcessW",
    }
)

_ENV_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "API")


@dataclass
class RiskAssessment:
    """Result of the static pre-flight scan of a code snippet."""

    level: str = RISK_SAFE
    reasons: list[str] = field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        return self.level in (RISK_DANGEROUS, RISK_DENIED)

    def describe(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "no elevated operations detected"


class CodeConfirmationRequired(Exception):
    """Raised when the active privilege mode demands explicit user confirmation."""

    def __init__(self, reasons: list[str], code: str) -> None:
        self.reasons = list(reasons)
        self.code = code
        super().__init__("; ".join(reasons))


class CodeExecutionDenied(Exception):
    """Raised when the code matches the hard deny-list (never executed)."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(reasons))


# ---------------------------------------------------------------------------
# Static risk assessment
# ---------------------------------------------------------------------------
def _scan_source_patterns(code: str) -> list[str]:
    """Detect dangerous substrings, including inside string literals (shell calls)."""
    reasons: list[str] = []
    for pattern, label in _DENIED_PATTERNS:
        if pattern.search(code):
            reasons.append(label)
    return reasons


def _collect_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return (imported top-level modules, called attribute/call names)."""
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
    return imports, calls


def assess_code_risk(code: str) -> RiskAssessment:
    """Statically classify a snippet by its most dangerous operation."""
    assessment = RiskAssessment()

    denied = _scan_source_patterns(code)
    if denied:
        assessment.level = RISK_DENIED
        assessment.reasons = [f"denied: {r}" for r in denied]
        return assessment

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        # Unparseable code cannot be assessed — treat as dangerous.
        assessment.level = RISK_DANGEROUS
        assessment.reasons = [f"unparseable code ({exc.msg})"]
        return assessment

    imports, calls = _collect_names(tree)

    if imports & _DANGEROUS_IMPORTS or calls & _DANGEROUS_CALLS:
        hit = sorted((imports & _DANGEROUS_IMPORTS) | (calls & _DANGEROUS_CALLS))
        assessment.level = RISK_DANGEROUS
        assessment.reasons = [f"dangerous operation: {', '.join(hit)}"]
        return assessment

    if imports & _ELEVATED_IMPORTS or calls & _ELEVATED_CALLS:
        hit = sorted((imports & _ELEVATED_IMPORTS) | (calls & _ELEVATED_CALLS))
        assessment.level = RISK_ELEVATED
        assessment.reasons = [f"elevated operation: {', '.join(hit)}"]
        return assessment

    return assessment


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------
def resolve_execution_mode(explicit: str | None = None) -> str:
    """Resolve the active privilege mode (explicit > env > balanced)."""
    candidate = (explicit or os.getenv("AVRORA_PC_EXECUTION_MODE", "")).strip().lower()
    if candidate in VALID_MODES:
        return candidate
    return MODE_BALANCED


def _requires_confirmation(level: str, mode: str) -> bool:
    """Decide whether a risk level needs explicit confirmation in this mode."""
    if level == RISK_DENIED:
        return True  # surfaced as a denial, handled by the caller
    if mode == MODE_TRUSTED:
        return False
    if mode == MODE_STRICT:
        return level in (RISK_ELEVATED, RISK_DANGEROUS)
    # balanced
    return level == RISK_DANGEROUS


# ---------------------------------------------------------------------------
# Sandboxed execution
# ---------------------------------------------------------------------------
def _sanitized_env() -> dict[str, str]:
    """Child environment with secret-looking variables removed."""
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if any(marker in upper for marker in _ENV_SECRET_MARKERS):
            env.pop(key, None)
    return env


def _creationflags() -> int:
    """Detached, windowless process group so the whole tree can be killed."""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminate the process and **all** its descendants (audit: RCE containment)."""
    if proc.poll() is not None:
        return
    # Preferred: psutil recursive kill (cross-platform, catches grandchildren).
    try:
        import psutil

        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception as _exc:  # noqa: BLE001
                    logger.debug("child kill failed: %s", _exc)
            parent.kill()
            return
        except psutil.NoSuchProcess:
            return
        except Exception as _exc:  # noqa: BLE001
            logger.debug("psutil tree kill failed, falling back: %s", _exc)
    except ImportError:
        logger.debug("psutil unavailable; using taskkill fallback")

    # Fallback: taskkill /T kills the tree on Windows; killpg elsewhere.
    if os.name == "nt":
        try:
            subprocess.run(
                f"taskkill /F /T /PID {proc.pid}",
                shell=True,  # nosec B602 — pid is an int, not user input
                capture_output=True,
                timeout=5,
            )
            return
        except Exception as _exc:  # noqa: BLE001
            logger.debug("taskkill fallback failed: %s", _exc)
    try:
        # POSIX-only: pyright's Windows-agnostic stubs may not expose these.
        os.killpg(os.getpgid(proc.pid), 9)  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass


def _watch_memory(proc: subprocess.Popen, max_memory_mb: int, stop_event: threading.Event) -> None:
    """Watchdog: kill the tree if the process exceeds the RSS budget."""
    try:
        import psutil
    except ImportError:
        return

    limit = max_memory_mb * 1024 * 1024
    try:
        ps = psutil.Process(proc.pid)
    except Exception:  # noqa: BLE001
        return
    while not stop_event.wait(0.5):
        if proc.poll() is not None:
            return
        try:
            total = ps.memory_info().rss + sum(
                c.memory_info().rss for c in ps.children(recursive=True) if c.is_running()
            )
        except Exception:  # noqa: BLE001
            return
        if total > limit:
            logger.warning(
                "Sandbox memory cap exceeded (%s MB > %s MB) — killing tree",
                total // (1024 * 1024),
                max_memory_mb,
            )
            _kill_process_tree(proc)
            return


def _strip_markdown_fences(code: str) -> str:
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    elif code.startswith("```"):
        code = code[len("```"):].strip()
    if code.endswith("```"):
        code = code[:-3].strip()
    return code


def run_python_code(
    code: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    mode: str | None = None,
    confirmed: bool = False,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
    cancel_event=None,
) -> str:
    """Execute LLM-generated Python in a contained subprocess.

    Raises:
        CodeExecutionDenied: the snippet matches the hard deny-list.
        CodeConfirmationRequired: the active mode requires user confirmation
            and ``confirmed`` is False.
    """
    if not code or not code.strip():
        return "Error: No code provided."

    mode = resolve_execution_mode(mode)
    code = _strip_markdown_fences(code)

    assessment = assess_code_risk(code)

    if assessment.level == RISK_DENIED:
        logger.warning("[code_interpreter] DENIED: %s", assessment.describe())
        raise CodeExecutionDenied(assessment.reasons)

    if not confirmed and _requires_confirmation(assessment.level, mode):
        raise CodeConfirmationRequired(assessment.reasons, code)

    try:
        from abilities.pc.repl_wrapper import PersistentREPL
    except ImportError:
        try:
            from core.repl_wrapper import PersistentREPL
        except ImportError:
            PersistentREPL = None
    def _truncate(text: str, limit: int = 4000) -> str:
        if not text or len(text) <= limit:
            return text
        half = limit // 2
        return f"{text[:half]}\n\n... [TRUNCADO: Salida demasiado larga] ...\n\n{text[-half:]}"

    # Use PersistentREPL for safe/elevated code to preserve memory between turns
    if assessment.level in (RISK_SAFE, RISK_ELEVATED):
        repl = PersistentREPL.get_instance()
        stdout, stderr = repl.run_code(code, timeout=timeout, cancel_event=cancel_event)
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            return "Error: la ejecución fue cancelada por el usuario (turn cancelled)."
            
        output: list[str] = []
        if stdout:
            output.append("STDOUT:\n" + _truncate(stdout))
        if stderr:
            output.append("STDERR:\n" + _truncate(stderr))
            
        if not output:
            return "Ejecución completada sin salida en consola."
        return "\n".join(output)

    # DANGEROUS mode operations run in an ephemeral sandbox to protect the REPL
    with tempfile.TemporaryDirectory(prefix="avrora_sbx_", ignore_cleanup_errors=True) as work_dir:
        script = Path(work_dir) / "avrora_snippet.py"
        script.write_text(code, encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, "-I", str(script)],
            cwd=work_dir,
            env=_sanitized_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creationflags(),
            start_new_session=(os.name != "nt"),
        )

        stop_event = threading.Event()
        if max_memory_mb > 0:
            threading.Thread(
                target=_watch_memory, args=(proc, max_memory_mb, stop_event), daemon=True
            ).start()

        timed_out = False
        user_cancelled = False
        start_time = time.perf_counter()
        try:
            while True:
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    user_cancelled = True
                    _kill_process_tree(proc)
                    try:
                        stdout, stderr = proc.communicate(timeout=2)
                    except Exception:  # noqa: BLE001
                        stdout, stderr = "", ""
                    break

                try:
                    stdout, stderr = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if time.perf_counter() - start_time > timeout:
                        timed_out = True
                        _kill_process_tree(proc)
                        try:
                            stdout, stderr = proc.communicate(timeout=5)
                        except Exception:  # noqa: BLE001
                            stdout, stderr = "", ""
                        break
        finally:
            stop_event.set()

        if user_cancelled:
            return "Error: la ejecución fue cancelada por el usuario (turn cancelled)."

        if timed_out:
            return (
                f"Error: el código excedió el tiempo límite de {timeout}s y el árbol de procesos "
                "fue terminado."
            )

        output: list[str] = []
        if stdout:
            output.append("STDOUT:\n" + _truncate(stdout))
        if stderr:
            output.append("STDERR:\n" + _truncate(stderr))

        if not output:
            if proc.returncode == 0:
                return "Ejecución completada sin salida en consola."
            return f"El script finalizó con código de error {proc.returncode}."

        return "\n".join(output)


def code_timeout_seconds() -> int:
    """Timeout from env (AVRORA_PC_CODE_TIMEOUT) with a sane fallback."""
    try:
        return max(1, int(os.getenv("AVRORA_PC_CODE_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def confirmation_message(reasons: list[str], mode: str) -> str:
    """Human-readable confirmation request shown before executing risky code."""
    detail = "; ".join(reasons) if reasons else "operaciones sensibles"
    return (
        f"[seguridad] El modo de privilegio actual («{mode}») exige confirmación explícita para "
        f"ejecutar este código ({detail}). Responde «confirmar» para proceder o «cancelar» para abortar."
    )

# Exposición de la herramienta para el framework de Avrora
CODE_INTERPRETER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pc_run_python_code",
        "description": "Ejecuta un script de Python de forma local. Úsalo para manipular archivos, interactuar con el sistema operativo o automatizar tareas complejas. AVISO CRÍTICO: NUNCA uses esta herramienta para ejecutar servidores o procesos en segundo plano (daemon). El Sandbox matará todos los procesos al terminar. Para tareas de larga duración, escribe un script físico y usa pc_run_command con async_mode=true. Retorna el stdout y stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "El código Python a ejecutar. Puede incluir múltiples líneas, imports y lógica completa."
                }
            },
            "required": ["code"],
            "additionalProperties": False
        }
    }
}
