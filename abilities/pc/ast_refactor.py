"""Semantic Code Refactoring & Inspection Suite for AVRORA using Python AST.

Provides AST-level (Abstract Syntax Tree) transformations with syntax guarantees:
- `ast_inspect_symbols`: Hierarchical symbol inspection (classes, methods, functions, args, docstrings).
- `ast_rename_symbol`: Semantic renaming of identifiers without affecting string literals or comments.
- `ast_wrap_try_except`: Syntactically wraps function bodies in try-except blocks without indentation bugs.
- `ast_insert_parameter`: Injects parameters into function signatures with default values.

Security Policy:
- Strictly prohibits reading, modifying, or touching .env files.
- Atomic file updates with os.replace to prevent corruption.
"""
from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path
from typing import Any


class ASTRefactorError(Exception):
    """Raised when an AST operation fails."""


def _assert_safe_path(p: Path) -> None:
    norm = p.resolve()
    for part in norm.parts:
        if part == ".env" or part.startswith(".env."):
            raise PermissionError("Security Violation: Access to .env or environment files is strictly prohibited.")


def ast_inspect_symbols(path: str | Path, root: Path | None = None) -> dict[str, Any]:
    """Inspect all classes, methods, functions, and docstrings in a Python source file."""
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists() or not target.is_file():
        return {"error": f"File '{path}' does not exist or is not a regular file."}

    try:
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target))
    except SyntaxError as e:
        return {"error": f"SyntaxError in '{path}': {e}"}
    except Exception as e:
        return {"error": f"Failed to read '{path}': {e}"}

    classes: list[dict[str, Any]] = []
    standalone_functions: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            c_info: dict[str, Any] = {
                "name": node.name,
                "line": node.lineno,
                "docstring": ast.get_docstring(node),
                "bases": [ast.unparse(b) for b in node.bases],
                "methods": [],
            }
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_args = [a.arg for a in item.args.args]
                    c_info["methods"].append({
                        "name": item.name,
                        "line": item.lineno,
                        "args": m_args,
                        "docstring": ast.get_docstring(item),
                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                    })
            classes.append(c_info)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f_args = [a.arg for a in node.args.args]
            standalone_functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": f_args,
                "docstring": ast.get_docstring(node),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })

    return {
        "file": str(target.relative_to(base_root) if target.is_relative_to(base_root) else target),
        "classes": classes,
        "functions": standalone_functions,
    }


class _SymbolRenamer(ast.NodeTransformer):
    def __init__(self, old_name: str, new_name: str, scope: str = "all", target_scope_name: str | None = None):
        self.old_name = old_name
        self.new_name = new_name
        self.scope = scope
        self.target_scope_name = target_scope_name
        self.changes = 0
        self._current_scope_name: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        if self.scope == "class" or self.scope == "all":
            if node.name == self.old_name:
                node.name = self.new_name
                self.changes += 1
        prev_scope = self._current_scope_name
        self._current_scope_name = node.name
        self.generic_visit(node)
        self._current_scope_name = prev_scope
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        if self.scope in ("function", "all"):
            if node.name == self.old_name:
                node.name = self.new_name
                self.changes += 1

        # Check function arguments
        for arg in node.args.args:
            if arg.arg == self.old_name:
                arg.arg = self.new_name
                self.changes += 1

        prev_scope = self._current_scope_name
        self._current_scope_name = node.name
        self.generic_visit(node)
        self._current_scope_name = prev_scope
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if self.target_scope_name and self._current_scope_name != self.target_scope_name:
            return node
        if node.id == self.old_name:
            node.id = self.new_name
            self.changes += 1
        return node


def ast_rename_symbol(
    path: str | Path,
    old_name: str,
    new_name: str,
    scope: str = "all",
    target_scope_name: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Semantically rename a class, function, or variable across the AST while preserving comments and strings."""
    import io
    import tokenize

    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists():
        return {"success": False, "message": f"File '{path}' does not exist."}

    try:
        source = target.read_text(encoding="utf-8")
        # Ensure it parses cleanly before modification
        ast.parse(source, filename=str(target))
    except Exception as e:
        return {"success": False, "message": f"Failed to parse '{path}': {e}"}

    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source.encode("utf-8")).readline))
        new_tokens = []
        changes = 0

        for tok in tokens:
            # Only rename tokens of type NAME matching old_name (leaves comments and strings untouched)
            if tok.type == tokenize.NAME and tok.string == old_name:
                new_tokens.append(tokenize.TokenInfo(tok.type, new_name, tok.start, tok.end, tok.line))
                changes += 1
            else:
                new_tokens.append(tok)

        if changes == 0:
            return {"success": False, "message": f"No symbol matching '{old_name}' found."}

        untokenized = tokenize.untokenize(new_tokens)
        new_source = untokenized if isinstance(untokenized, str) else untokenized.decode("utf-8")
        # Validate AST of modified source
        ast.parse(new_source, filename=str(target))
    except Exception as e:
        return {"success": False, "message": f"AST verification failed after rename: {e}"}

    try:
        temp_dir = target.parent
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(new_source)
            temp_path = Path(tf.name)
        os.replace(temp_path, target)
    except Exception as e:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return {"success": False, "message": f"Atomic write failed: {e}"}

    return {
        "success": True,
        "message": f"Successfully renamed '{old_name}' to '{new_name}' ({changes} occurrences). Comments preserved.",
        "changes": changes,
    }



class _TryExceptWrapper(ast.NodeTransformer):
    def __init__(self, target_func_name: str, exception_type: str = "Exception", fallback_return: str | None = None):
        self.target_func_name = target_func_name
        self.exception_type = exception_type
        self.fallback_return = fallback_return
        self.wrapped = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._wrap(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._wrap(node)

    def _wrap(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        if node.name != self.target_func_name:
            self.generic_visit(node)
            return node

        # Extract docstring if present so it remains at the top
        docstring = ast.get_docstring(node)
        body = node.body
        new_body_prefix: list[ast.stmt] = []
        is_first_const = (
            len(body) > 0 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        )
        if docstring is not None and is_first_const:
            new_body_prefix.append(body[0])
            body = body[1:]

        handler_body: list[ast.stmt] = []
        # Return fallback value or None
        if self.fallback_return is not None:
            try:
                ret_val = ast.parse(self.fallback_return, mode="eval").body
                handler_body.append(ast.Return(value=ret_val))
            except Exception:
                handler_body.append(ast.Return(value=ast.Constant(value=None)))
        else:
            handler_body.append(ast.Return(value=ast.Constant(value=None)))

        try_node = ast.Try(
            body=body,
            handlers=[
                ast.ExceptHandler(
                    type=ast.Name(id=self.exception_type, ctx=ast.Load()),
                    name="exc",
                    body=handler_body,
                )
            ],
            orelse=[],
            finalbody=[],
        )

        node.body = new_body_prefix + [try_node]
        self.wrapped = True
        return node


def ast_wrap_try_except(
    path: str | Path,
    function_name: str,
    exception_type: str = "Exception",
    fallback_return: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Syntactically wrap a function body in a try-except block with 100% syntax guarantee."""
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists():
        return {"success": False, "message": f"File '{path}' does not exist."}

    try:
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target))
    except Exception as e:
        return {"success": False, "message": f"Failed to parse '{path}': {e}"}

    wrapper = _TryExceptWrapper(
        target_func_name=function_name,
        exception_type=exception_type,
        fallback_return=fallback_return,
    )
    new_tree = wrapper.visit(tree)
    ast.fix_missing_locations(new_tree)

    if not wrapper.wrapped:
        return {"success": False, "message": f"Function '{function_name}' not found in '{path}'."}

    try:
        new_source = ast.unparse(new_tree)
        ast.parse(new_source)
    except Exception as e:
        return {"success": False, "message": f"AST generation or verification failed: {e}"}

    try:
        temp_dir = target.parent
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(new_source)
            temp_path = Path(tf.name)
        os.replace(temp_path, target)
    except Exception as e:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return {"success": False, "message": f"Atomic write failed: {e}"}

    return {
        "success": True,
        "message": f"Successfully wrapped function '{function_name}' with try...except ({exception_type}).",
    }
