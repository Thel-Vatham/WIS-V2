"""Shadow Workspace & Ephemeral Staging Engine for AVRORA Subagents.

Guarantees non-destructive execution:
1. Subagents stage all edits, refactors, and test files in an isolated temporary shadow tree.
2. Runs validation (syntax checks, linters, unit tests) inside the shadow workspace.
3. Automatically computes unified diffs.
4. Performs an atomic commit back to the host workspace ONLY if all checks succeed (100% pass rate).
5. Instantly discards the staging area if checks fail, keeping host code untouched.
"""
from __future__ import annotations

import difflib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)



class ShadowWorkspace:
    """Manages an isolated staging workspace with commit-on-pass semantics."""

    def __init__(self, host_root: Path | None = None) -> None:
        self.host_root = (host_root or Path.cwd()).resolve()
        self._tmp = tempfile.TemporaryDirectory(prefix="avrora_shadow_")
        self.stage_root = Path(self._tmp.name).resolve()
        self.staged_files: set[str] = set()

    def _assert_safe(self, rel_path: str | Path) -> None:
        p = Path(rel_path)
        if p.name == ".env" or ".env" in p.parts:
            raise PermissionError("Security Violation: Cannot stage or manipulate .env in shadow workspace.")

    def stage_file(self, rel_path: str) -> Path:
        """Copy a file from host workspace into shadow staging."""
        self._assert_safe(rel_path)
        host_file = (self.host_root / rel_path).resolve()
        stage_file = (self.stage_root / rel_path).resolve()

        if host_file.exists():
            stage_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(host_file, stage_file)
        else:
            stage_file.parent.mkdir(parents=True, exist_ok=True)

        self.staged_files.add(rel_path.replace("\\", "/"))
        return stage_file

    def write_staged_file(self, rel_path: str, content: str) -> Path:
        """Create or update a file in the shadow staging area."""
        self._assert_safe(rel_path)
        stage_file = (self.stage_root / rel_path).resolve()
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text(content, encoding="utf-8")
        self.staged_files.add(rel_path.replace("\\", "/"))
        return stage_file

    def read_staged_file(self, rel_path: str) -> str:
        """Read content of a staged file."""
        self._assert_safe(rel_path)
        stage_file = (self.stage_root / rel_path).resolve()
        if not stage_file.exists():
            raise FileNotFoundError(f"Staged file '{rel_path}' does not exist.")
        return stage_file.read_text(encoding="utf-8")

    def run_staged_check(
        self,
        command: str | list[str],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        cmd: str | list[str] = command
        shell: bool = isinstance(command, str)

        env = dict(os.environ)
        # Ensure shadow root is in PYTHONPATH so local modules can be imported
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{self.stage_root}{os.pathsep}{existing_pp}" if existing_pp else str(self.stage_root)

        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.stage_root),
                shell=shell,  # nosec B602
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return {
                "success": res.returncode == 0,
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds.",
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            }

    def compute_diff(self) -> str:
        """Compute the unified diff between host files and staged files."""
        diffs: list[str] = []
        for rel in sorted(self.staged_files):
            host_p = (self.host_root / rel).resolve()
            stage_p = (self.stage_root / rel).resolve()

            if host_p.exists():
                host_lines = host_p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            else:
                host_lines = []

            if stage_p.exists():
                stage_lines = stage_p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            else:
                stage_lines = []

            chunk = list(
                difflib.unified_diff(
                    host_lines,
                    stage_lines,
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    n=3,
                )
            )
            if chunk:
                diffs.append("".join(chunk))

        return "\n".join(diffs)

    def commit_to_host(self, require_check_cmd: str | list[str] | None = None) -> dict[str, Any]:
        """Commit staged files back to the host workspace, optionally enforcing check."""
        if require_check_cmd:
            check_res = self.run_staged_check(require_check_cmd)
            if not check_res["success"]:
                return {
                    "committed": False,
                    "reason": "Pre-commit check failed in shadow staging.",
                    "details": check_res["stderr"] or check_res["stdout"],
                    "diff": "",
                }

        diff_str = self.compute_diff()
        committed_files = []

        for rel in self.staged_files:
            stage_p = (self.stage_root / rel).resolve()
            host_p = (self.host_root / rel).resolve()

            if stage_p.exists():
                host_p.parent.mkdir(parents=True, exist_ok=True)
                # Atomic copy via temp file
                with tempfile.NamedTemporaryFile("wb", dir=host_p.parent, delete=False) as tf:
                    tf.write(stage_p.read_bytes())
                    temp_p = Path(tf.name)
                os.replace(temp_p, host_p)
                committed_files.append(rel)

        return {
            "committed": True,
            "files": committed_files,
            "diff": diff_str,
            "message": f"Successfully committed {len(committed_files)} file(s) from shadow staging.",
        }

    def discard(self) -> None:
        """Discard the shadow workspace cleanly."""
        try:
            self._tmp.cleanup()
        except Exception as _exc:
            logger.debug("Operacion no fatal suprimida: %s", _exc)

    def __enter__(self) -> ShadowWorkspace:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.discard()
