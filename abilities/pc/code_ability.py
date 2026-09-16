"""
WIS Code Ability - Full Antigravity Surgical Toolkit.
Exposes the full code_tools.py suite as a first-class WIS Ability.
"""
from __future__ import annotations
import asyncio
from abilities.base import Ability
from .code_tools import (
    code_view_file, code_replace_content, code_grep,
    code_list_dir, code_write_file, code_multi_replace,
    CodeToolError,
)
from .code_interpreter import run_python_code
from .ast_refactor import ast_inspect_symbols, ast_rename_symbol


class CodeToolsAbility(Ability):
    """Antigravity-grade surgical code tools for WIS."""

    @property
    def name(self):
        return "code_tools"

    @property
    def description(self):
        return (
            "Surgical Antigravity code tools: view files by line range, grep/search codebase, "
            "atomic surgical replacement of code blocks, write new files, list directories, run Python. "
            "ALWAYS prefer code_replace_content over rewriting entire files. "
            "ALWAYS prefer code_grep over reading files blindly."
        )

    @property
    def domain(self):
        return "pc"

    def get_schema(self):
        return [
            {
                "action": "code_view_file",
                "description": "View file with line numbers. page with start_line/end_line.",
                "params": {"path": "file path", "start_line": "optional int", "end_line": "optional int"}
            },
            {
                "action": "code_grep",
                "description": "Fast codebase search returning matching lines with context.",
                "params": {"pattern": "search string", "path": "dir or file", "file_pattern": "*.py", "context_lines": "int", "is_regex": "true/false"}
            },
            {
                "action": "code_replace_content",
                "description": "Atomically replace an EXACT block in a file. Always prefer over full-rewrite.",
                "params": {"path": "file", "target_content": "exact text to replace", "replacement_content": "new text"}
            },
            {
                "action": "code_multi_replace",
                "description": "Multiple replacements in one atomic transaction.",
                "params": {"path": "file", "replacements": "list of objects with target_content and replacement_content keys"}
            },
            {
                "action": "code_write_file",
                "description": "Create new file safely. Pass overwrite=true to replace.",
                "params": {"path": "file path", "content": "file content", "overwrite": "true or false"}
            },
            {
                "action": "code_list_dir",
                "description": "List directory tree with file sizes.",
                "params": {"path": "dir path", "depth": "int depth"}
            },
            {
                "action": "run_python",
                "description": "Execute Python snippet, capture stdout and stderr.",
                "params": {"code": "python code string", "timeout": "seconds int"}
            },
            {
                "action": "ast_inspect_symbols",
                "description": "Inspect classes and methods in a Python file.",
                "params": {"path": "file path"}
            },
            {
                "action": "ast_rename_symbol",
                "description": "Rename an identifier in Python via AST.",
                "params": {"path": "file", "old_name": "str", "new_name": "str", "scope": "all or class or function"}
            },
        ]

    async def execute(self, action, params):
        try:
            a = (action or "").lower().strip()

            if a == "code_view_file":
                r = await asyncio.to_thread(
                    code_view_file,
                    params.get("path", ""),
                    int(params.get("start_line", 1)),
                    int(params["end_line"]) if "end_line" in params else None,
                )
                return {"success": True, "data": r, "message": r}

            if a == "code_grep":
                r = await asyncio.to_thread(
                    code_grep,
                    params.get("pattern", ""),
                    params.get("path", "."),
                    params.get("file_pattern", "*.py"),
                    int(params.get("context_lines", 2)),
                    str(params.get("is_regex", "false")).lower() == "true",
                )
                return {"success": True, "data": r, "message": r}

            if a == "code_replace_content":
                r = await asyncio.to_thread(
                    code_replace_content,
                    params.get("path", ""),
                    params.get("target_content", ""),
                    params.get("replacement_content", ""),
                )
                return {"success": True, "data": r, "message": r}

            if a == "code_multi_replace":
                r = await asyncio.to_thread(
                    code_multi_replace,
                    params.get("path", ""),
                    params.get("replacements", []),
                )
                return {"success": True, "data": r, "message": r}

            if a == "code_write_file":
                r = await asyncio.to_thread(
                    code_write_file,
                    params.get("path", ""),
                    params.get("content", ""),
                    str(params.get("overwrite", "false")).lower() == "true",
                )
                return {"success": True, "data": r, "message": r}

            if a == "code_list_dir":
                r = await asyncio.to_thread(
                    code_list_dir,
                    params.get("path", "."),
                    int(params.get("depth", 2)),
                )
                return {"success": True, "data": r, "message": r}

            if a == "run_python":
                r = await asyncio.to_thread(
                    run_python_code,
                    params.get("code", ""),
                    timeout=int(params.get("timeout", 30)),
                )
                if not isinstance(r, dict):
                    r = {"returncode": 1, "stdout": "", "stderr": str(r)}
                ok = r.get("returncode", 1) == 0
                return {"success": ok, "data": r, "message": r.get("stdout", "") + r.get("stderr", "")}

            if a == "ast_inspect_symbols":
                r = ast_inspect_symbols(params.get("path", ""))
                if "error" in r:
                    return {"success": False, "message": r["error"]}
                return {"success": True, "data": r}

            if a == "ast_rename_symbol":
                r = ast_rename_symbol(
                    params.get("path", ""),
                    params.get("old_name", ""),
                    params.get("new_name", ""),
                    params.get("scope", "all"),
                    params.get("target_scope_name"),
                )
                if isinstance(r, dict) and "error" in r:
                    return {"success": False, "message": r["error"]}
                return {"success": True, "message": str(r)}

            return {"success": False, "message": f"Unknown action: {action}"}

        except CodeToolError as e:
            return {"success": False, "message": f"Code tool error: {e}"}
        except Exception as e:
            return {"success": False, "message": str(e)}


# Backwards-compat alias
CodeAbility = CodeToolsAbility
