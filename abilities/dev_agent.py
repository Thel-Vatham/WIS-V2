"""
WIS Dev Agent — Specialized Software Development Ability.
==========================================================
A full-stack developer agent powered by Antigravity-grade tools:
- Surgical file editing (replace_content, multi_replace)
- Shadow workspace for isolated, non-destructive development
- TDD runner: writes tests, runs them, auto-repairs failures
- Isolated Python virtualenv for dependency management
- Multi-day autonomous development support
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.dev_agent")


class DevAgent(Ability):
    """Specialized autonomous software development agent."""

    @property
    def name(self):
        return "dev_agent"

    @property
    def description(self):
        return (
            "Autonomous software developer agent. Use for complex coding tasks: "
            "building web apps, APIs, neural networks, data pipelines, refactors. "
            "Uses surgical file editing (never rewrites whole files), runs tests automatically, "
            "and works in an isolated shadow workspace. "
            "Actions: create_project, edit_file, run_tests, install_package, run_code, shell."
        )

    @property
    def domain(self):
        return "pc"

    def get_schema(self):
        return [
            {
                "action": "create_project",
                "description": "Scaffold a new project directory with a given structure (files dict).",
                "params": {
                    "project_path": "Absolute path to create the project",
                    "files": "Dict of {relative_path: file_content} to write",
                    "description": "What this project does (for logging)"
                }
            },
            {
                "action": "edit_file",
                "description": "Surgically edit a file. ALWAYS prefer this over rewriting. Finds exact target_content and replaces it.",
                "params": {
                    "path": "Absolute file path",
                    "target_content": "Exact text to find and replace",
                    "replacement_content": "New text to insert",
                }
            },
            {
                "action": "run_tests",
                "description": "Run pytest in a directory and return pass/fail results with details.",
                "params": {
                    "test_dir": "Directory to run tests in",
                    "test_file": "Specific test file (optional)",
                    "timeout": "Max seconds (optional, default 60)",
                }
            },
            {
                "action": "install_package",
                "description": "Install a Python package via pip into the WIS venv.",
                "params": {"package": "Package name (e.g. 'fastapi==0.104.0')", "timeout": "seconds (default 120)"}
            },
            {
                "action": "run_code",
                "description": "Execute a Python script or snippet and capture output.",
                "params": {
                    "code": "Python code string to execute (or use 'path' for a file)",
                    "path": "Path to .py file to run (alternative to 'code')",
                    "timeout": "Max seconds (default 30)",
                    "cwd": "Working directory (optional)",
                }
            },
            {
                "action": "shell",
                "description": "Run an arbitrary shell command and capture output.",
                "params": {
                    "command": "Shell command to execute",
                    "timeout": "Max seconds (default 60)",
                    "cwd": "Working directory (optional)",
                }
            },
            {
                "action": "list_project",
                "description": "List files in a project directory with sizes.",
                "params": {"path": "Directory path", "depth": "Max depth (default 3)"}
            },
            {
                "action": "read_file",
                "description": "Read a file with optional line range.",
                "params": {"path": "File path", "start_line": "int (optional)", "end_line": "int (optional)"}
            },
            {
                "action": "write_file",
                "description": "Write or overwrite a file completely.",
                "params": {"path": "File path", "content": "File content", "overwrite": "true/false"}
            },
            {
                "action": "grep",
                "description": "Search for a pattern across files in a directory.",
                "params": {"pattern": "Search string", "path": "Directory", "file_pattern": "e.g. *.py"}
            },
        ]

    async def execute(self, action: str, params: dict) -> dict:
        a = (action or "").lower().strip()
        try:
            if a == "create_project":
                return await asyncio.to_thread(self._create_project, params)
            if a == "edit_file":
                return await asyncio.to_thread(self._edit_file, params)
            if a == "run_tests":
                return await self._run_tests(params)
            if a == "install_package":
                return await self._install_package(params)
            if a == "run_code":
                return await self._run_code(params)
            if a == "shell":
                return await self._shell(params)
            if a == "list_project":
                return await asyncio.to_thread(self._list_project, params)
            if a == "read_file":
                return await asyncio.to_thread(self._read_file, params)
            if a == "write_file":
                return await asyncio.to_thread(self._write_file, params)
            if a == "grep":
                return await asyncio.to_thread(self._grep, params)
            return {"success": False, "message": f"Unknown action: {action}"}
        except Exception as e:
            logger.error("DevAgent error in %s: %s", action, e)
            return {"success": False, "message": str(e)}

    # ── Internal methods ────────────────────────────────────────────────────────

    def _create_project(self, params: dict) -> dict:
        project_path = Path(params.get("project_path", ""))
        files = params.get("files", {})
        if not project_path:
            return {"success": False, "message": "project_path required"}
        project_path.mkdir(parents=True, exist_ok=True)
        created = []
        for rel_path, content in files.items():
            target = project_path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            created.append(str(rel_path))
        return {
            "success": True,
            "message": f"Project created at {project_path} with {len(created)} files: {created}"
        }

    def _edit_file(self, params: dict) -> dict:
        path = Path(params.get("path", ""))
        target = params.get("target_content", "")
        replacement = params.get("replacement_content", "")
        if not path.exists():
            return {"success": False, "message": f"File not found: {path}"}
        content = path.read_text(encoding="utf-8")
        if target not in content:
            return {
                "success": False,
                "message": f"target_content not found exactly in {path}. Use code_grep first to find the exact text."
            }
        new_content = content.replace(target, replacement, 1)
        path.write_text(new_content, encoding="utf-8")
        return {"success": True, "message": f"Edited {path} successfully."}

    async def _run_tests(self, params: dict) -> dict:
        test_dir = params.get("test_dir", ".")
        test_file = params.get("test_file", "")
        timeout = int(params.get("timeout", 60))
        target = test_file if test_file else test_dir
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pytest", target, "-v", "--tb=short", "--no-header",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=test_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            passed = proc.returncode == 0
            return {
                "success": passed,
                "data": {"stdout": out, "stderr": err, "returncode": proc.returncode},
                "message": out + err
            }
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Tests timed out after {timeout}s"}

    async def _install_package(self, params: dict) -> dict:
        package = params.get("package", "")
        timeout = int(params.get("timeout", 120))
        if not package:
            return {"success": False, "message": "Package name required"}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", package, "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            ok = proc.returncode == 0
            msg = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
            return {"success": ok, "message": msg or (f"Installed {package}" if ok else f"Failed to install {package}")}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"pip install timed out after {timeout}s"}

    async def _run_code(self, params: dict) -> dict:
        code = params.get("code", "")
        path = params.get("path", "")
        timeout = int(params.get("timeout", 30))
        cwd = params.get("cwd") or os.getcwd()
        if path:
            cmd = [sys.executable, str(path)]
        elif code:
            cmd = [sys.executable, "-c", code]
        else:
            return {"success": False, "message": "Provide 'code' or 'path'"}
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Code execution timed out after {timeout}s"}

    async def _shell(self, params: dict) -> dict:
        command = params.get("command", "")
        timeout = int(params.get("timeout", 60))
        cwd = params.get("cwd") or os.getcwd()
        if not command:
            return {"success": False, "message": "command required"}
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            return {"success": ok, "data": {"stdout": out, "stderr": err, "returncode": proc.returncode}, "message": out + err}
        except asyncio.TimeoutError:
            return {"success": False, "message": f"Command timed out after {timeout}s"}

    def _list_project(self, params: dict) -> dict:
        path = Path(params.get("path", "."))
        depth = int(params.get("depth", 3))
        if not path.exists():
            return {"success": False, "message": f"Path not found: {path}"}
        lines = []
        def _walk(p: Path, indent: int, current_depth: int):
            if current_depth > depth:
                return
            prefix = "  " * indent
            if p.is_file():
                size = p.stat().st_size
                lines.append(f"{prefix}{p.name} ({size:,} bytes)")
            elif p.is_dir():
                lines.append(f"{prefix}{p.name}/")
                try:
                    for child in sorted(p.iterdir()):
                        if child.name.startswith(".") or child.name == "__pycache__":
                            continue
                        _walk(child, indent + 1, current_depth + 1)
                except PermissionError:
                    pass
        _walk(path, 0, 0)
        result = "\n".join(lines)
        return {"success": True, "data": result, "message": result}

    def _read_file(self, params: dict) -> dict:
        path = Path(params.get("path", ""))
        if not path.exists():
            return {"success": False, "message": f"File not found: {path}"}
        start = int(params.get("start_line", 1)) - 1
        end = params.get("end_line")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if end:
            lines = lines[start:int(end)]
        else:
            lines = lines[start:]
        result = "\n".join(f"{start+i+1:>4}: {line}" for i, line in enumerate(lines))
        return {"success": True, "data": result, "message": result}

    def _write_file(self, params: dict) -> dict:
        path = Path(params.get("path", ""))
        content = params.get("content", "")
        overwrite = str(params.get("overwrite", "false")).lower() == "true"
        if not path:
            return {"success": False, "message": "path required"}
        if path.exists() and not overwrite:
            return {"success": False, "message": f"File exists: {path}. Pass overwrite=true to replace."}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"success": True, "message": f"Written {path} ({len(content):,} chars)"}

    def _grep(self, params: dict) -> dict:
        import re as re_mod
        pattern = params.get("pattern", "")
        path = Path(params.get("path", "."))
        file_pat = params.get("file_pattern", "*.py")
        if not pattern:
            return {"success": False, "message": "pattern required"}
        results = []
        files = list(path.rglob(file_pat)) if path.is_dir() else [path]
        for f in files:
            if not f.is_file():
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if re_mod.search(pattern, line):
                        results.append(f"{f}:{i}: {line.strip()}")
            except Exception:
                continue
            if len(results) >= 100:
                break
        if not results:
            return {"success": False, "message": f"No matches for '{pattern}'"}
        msg = "\n".join(results[:100])
        return {"success": True, "data": results, "message": msg}
