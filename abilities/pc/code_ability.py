"""
WIS Code Ability.
Wraps AVRORA's code interpreter and AST refactoring into a WIS Ability.
"""
from __future__ import annotations

import json
from typing import Any
from abilities.base import Ability

from .code_interpreter import run_python_code
from .ast_refactor import ast_inspect_symbols, ast_rename_symbol, ast_wrap_try_except

class CodeAbility(Ability):
    @property
    def name(self) -> str:
        return "code_tools"

    @property
    def description(self) -> str:
        return "Run python code and perform AST-level codebase refactoring."

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "ast_inspect_symbols",
                "description": "Inspect classes, methods, and functions in a python file.",
                "params": {"path": "File path to inspect"}
            },
            {
                "action": "ast_rename_symbol",
                "description": "Semantically rename a symbol in a python file.",
                "params": {
                    "path": "File path",
                    "old_name": "Identifier to find",
                    "new_name": "New identifier",
                    "scope": "Scope to apply ('all', 'class', 'function')",
                    "target_scope_name": "Name of the class/func if scope is not 'all'"
                }
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            if action == "ast_inspect_symbols":
                path = params.get("path", "")
                result = ast_inspect_symbols(path)
                if "error" in result:
                    return {"success": False, "message": result["error"]}
                return {"success": True, "data": result, "message": "Symbols inspected"}
                
            elif action == "ast_rename_symbol":
                path = params.get("path", "")
                old_name = params.get("old_name", "")
                new_name = params.get("new_name", "")
                scope = params.get("scope", "all")
                target = params.get("target_scope_name")
                
                result = ast_rename_symbol(path, old_name, new_name, scope, target)
                if isinstance(result, dict) and "error" in result:
                    return {"success": False, "message": result["error"]}
                return {"success": True, "message": f"Symbol renamed. {result}"}
                
            return {"success": False, "message": f"Unknown action: {action}"}
            
        except Exception as e:
            return {"success": False, "message": str(e)}
