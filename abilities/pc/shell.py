"""Safe shell execution and real-time streaming execution for Windows.

Handles automatic path quoting for paths with spaces (e.g. 'C:\\Users\\Area Tecnica Summa\\...'),
execution timeouts, synchronous captured output, and real-time streaming execution
via non-blocking line callbacks for long-running build commands and scripts.
"""
from __future__ import annotations

import logging
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)



class PCOperationError(Exception):
    """Raised when a PC operation fails."""


# Looks like a Windows absolute path start: "C:\..." or UNC "\\...".
_ABS_PATH_START = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")
# Command separators: a path-with-spaces run stops before these.
_SEPARATORS = ("&&", "||", ";", "|", ">", "<", "2>", "1>")


def _quote_paths(command: str) -> str:
    """Quote unquoted Windows absolute paths that contain spaces.

    Fixes the real bug where a home with spaces ("C:\\Users\\Area Tecnica
    Summa") is split by the shell at the first space, truncating every path
    to "C:\\Users\\Area". Existing quotes are preserved; only the path run
    (up to a command separator) is wrapped.
    """
    out: list[str] = []
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch in "\"'":
            quote = ch
            j = command.find(quote, i + 1)
            end = n if j == -1 else j + 1
            out.append(command[i:end])
            i = end
            continue
        if ch.isspace():
            out.append(ch)
            i += 1
            continue
        # Unquoted token start.
        j = i
        while j < n and not command[j].isspace() and command[j] not in "\"'":
            j += 1
        token = command[i:j]
        if _ABS_PATH_START.match(token):
            # Consume the whole path run (spaces included) until a separator
            # or a quote — the model wrote "C:\Users\Area Tecnica Summa\...".
            k = j
            run = token
            while k < n:
                rest = command[k:]
                if any(rest.startswith(sep) for sep in _SEPARATORS) or command[k] in "\"'":
                    break
                run += command[k]
                k += 1
            out.append(f'"{run}"' if " " in run else run)
            i = k
        else:
            out.append(token)
            i = j
    return "".join(out)


class ShellOps:
    """Safe shell execution with timeout and captured output."""

    @staticmethod
    def run(
        command: str,
        timeout: float | int = 30,
        cwd: str | None = None,
        cancel_event: Any = None,
    ) -> str:
        safe = _quote_paths(command)
        try:
            proc = subprocess.Popen(
                safe,
                shell=True,  # nosec B602
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001
            raise PCOperationError(f"could not run command: {exc}") from exc

        import time

        start = time.perf_counter()
        stdout = ""
        stderr = ""
        while True:
            # Responsive cancellation: kill immediately if turn was stopped
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                try:
                    proc.kill()
                    subprocess.run(
                        f"taskkill /F /T /PID {proc.pid}",
                        shell=True,
                        capture_output=True,
                        timeout=2.0,
                    )
                except Exception as _exc:
                    logger.debug("Operacion no fatal suprimida al cancelar subproceso: %s", _exc)
                raise PCOperationError("command cancelled by user")

            rem = float(timeout) - (time.perf_counter() - start)
            if rem <= 0:
                try:
                    proc.kill()
                    subprocess.run(
                        f"taskkill /F /T /PID {proc.pid}",
                        shell=True,
                        capture_output=True,
                        timeout=2.0,
                    )
                except Exception as _exc:
                    logger.debug("Operacion no fatal suprimida al vencer timeout: %s", _exc)
                raise PCOperationError(f"command timed out after {timeout}s")

            try:
                # communicate drains stdout/stderr buffers concurrently without deadlocks
                stdout, stderr = proc.communicate(timeout=min(0.2, max(0.01, rem)))
                break
            except subprocess.TimeoutExpired:
                continue

        out = (stdout or "").strip()
        err = (stderr or "").strip()
        if proc.returncode != 0:
            raise PCOperationError(f"exit {proc.returncode}: {err or out}")
        return out or "(ok, exit 0)"

    @staticmethod
    def run_streaming(
        command: str,
        callback: Any = None,
        timeout: float | int = 60,
        cwd: str | None = None,
    ) -> str:
        """Execute command streaming output line-by-line in real time.

        Allows long-running build commands and tools to report live progress.
        """
        import queue
        import threading
        import time

        safe = _quote_paths(command)
        collected_lines: list[str] = []
        try:
            proc = subprocess.Popen(
                safe,
                shell=True,  # nosec B602
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                cwd=cwd,
            )
            line_queue: queue.Queue[str | None] = queue.Queue()

            def _reader() -> None:
                try:
                    if proc.stdout:
                        for line in iter(proc.stdout.readline, ""):
                            line_queue.put(line)
                except Exception as _exc:
                    logger.debug("Operacion no fatal suprimida: %s", _exc)
                finally:
                    line_queue.put(None)

            t = threading.Thread(target=_reader, daemon=True)
            t.start()

            start = time.perf_counter()
            while True:
                remaining = timeout - (time.perf_counter() - start)
                if remaining <= 0:
                    try:
                        proc.kill()
                    except Exception as _exc:
                        logger.debug("Operacion no fatal suprimida: %s", _exc)
                    raise PCOperationError(f"streaming command timed out after {timeout}s")
                try:
                    item = line_queue.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    if proc.poll() is not None and line_queue.empty():
                        break
                    continue

                if item is None:
                    break

                clean_line = item.rstrip()
                collected_lines.append(clean_line)
                if callback and callable(callback):
                    try:
                        callback(clean_line)
                    except Exception as _exc:
                        logger.debug("Operacion no fatal suprimida: %s", _exc)

            try:
                rc = proc.wait(timeout=2.0) if proc.poll() is None else proc.poll() or 0
            except Exception:
                rc = proc.poll() or 0

            if rc != 0:
                tail = "\n".join(collected_lines[-5:])
                raise PCOperationError(f"exit {rc}: {tail}")
            return "\n".join(collected_lines) or "(ok, exit 0)"
        except PCOperationError:
            raise
        except Exception as exc:
            raise PCOperationError(f"could not stream command '{command}': {exc}") from exc
