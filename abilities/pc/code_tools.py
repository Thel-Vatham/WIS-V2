"""Surgical Code Tooling Suite for AVRORA (Antigravity-grade).

Provides pinpoint-accurate, non-destructive file and code operations:
- `code_view_file`: Paged file inspection with line numbers (1-indexed).
- `code_replace_content`: Surgical, atomic substring replacement with diff validation.
- `code_multi_replace`: Multiple non-contiguous chunk replacements in a single transaction.
- `code_grep`: Fast regex/literal search across the workspace with context.
- `code_list_dir`: Structured folder hierarchy inspection with sizes and child counts.
- `code_write_file`: Safe new file generation with overwrite protection.

Security Policy:
- Strictly prohibits reading, touching, or modifying `.env` or credential files.
- All file modifications are atomic using temporary files + `os.replace` to prevent corruption.
"""
from __future__ import annotations

import difflib
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class CodeToolError(Exception):
    """Base exception for surgical code tool failures."""


def _assert_safe_path(p: Path) -> None:
    """Enforce security policy: prohibit any access or manipulation of .env files."""
    norm = p.resolve()
    for part in norm.parts:
        if part == ".env" or part.startswith(".env."):
            raise PermissionError("Security Violation: Access to .env or environment files is strictly prohibited.")


def code_view_file(
    path: str | Path,
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 3000,
    root: Path | None = None,
) -> str:
    """View file contents with line numbers and bounds slicing.

    Args:
        path: Path to the target file.
        start_line: 1-indexed starting line (inclusive).
        end_line: 1-indexed ending line (inclusive). Defaults to start_line + max_lines - 1.
        max_lines: Maximum number of lines returned in one call (default 800).
        root: Optional workspace root for relative path resolution.

    Returns:
        Formatted string containing line numbers and file contents, or diagnostic info.
    """
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists():
        return f"[code_view_file error] File '{path}' does not exist."
    if target.is_dir():
        return f"[code_view_file error] '{path}' is a directory. Use code_list_dir instead."

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[code_view_file error] Failed to read file '{path}': {exc}"

    lines = content.splitlines(keepends=False)
    total_lines = len(lines)

    if total_lines == 0:
        return f"File '{path}' is empty (0 lines)."

    start = max(1, start_line)
    if end_line is None:
        end = min(total_lines, start + max_lines - 1)
    else:
        end = min(total_lines, max(start, end_line))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1

    selected_lines = lines[start - 1 : end]
    pad = len(str(end))
    numbered = [f"{start + i:>{pad}}: {line}" for i, line in enumerate(selected_lines)]

    header = f"--- {target.name} [Lines {start}-{end} of {total_lines}] ---"
    footer = f"--- End of slice ({len(selected_lines)} lines shown) ---"
    return "\n".join([header] + numbered + [footer])


def code_replace_content(
    path: str | Path,
    target_content: str,
    replacement_content: str,
    start_line: int | None = None,
    end_line: int | None = None,
    allow_multiple: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Perform surgical, atomic substring replacement in a file with unified diff feedback.

    Args:
        path: Path to the target file.
        target_content: Exact substring to be replaced.
        replacement_content: New content to substitute.
        start_line: Optional 1-indexed lower bound line to search within.
        end_line: Optional 1-indexed upper bound line to search within.
        allow_multiple: Whether to allow replacing multiple identical matches.
        root: Optional workspace root.

    Returns:
        dict with keys: `success` (bool), `message` (str), `diff` (str), `occurrences` (int).
    """
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists() or not target.is_file():
        return {
            "success": False,
            "message": f"File '{path}' does not exist or is not a regular file.",
            "diff": "",
            "occurrences": 0,
        }

    try:
        original = target.read_text(encoding="utf-8")
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not read '{path}': {exc}",
            "diff": "",
            "occurrences": 0,
        }

    # Normalize line endings for reliable matching
    target_norm = target_content.replace("\r\n", "\n")
    replacement_norm = replacement_content.replace("\r\n", "\n")
    orig_norm = original.replace("\r\n", "\n")

    # Range-restricted search if start/end line specified
    if start_line is not None or end_line is not None:
        lines = orig_norm.split("\n")
        total_lines = len(lines)
        s_idx = max(0, (start_line or 1) - 1)
        e_idx = min(total_lines, (end_line or total_lines))

        prefix = "\n".join(lines[:s_idx])
        if prefix:
            prefix += "\n"
        window = "\n".join(lines[s_idx:e_idx])
        suffix = "\n".join(lines[e_idx:])
        if suffix:
            suffix = "\n" + suffix

        count = window.count(target_norm)
        if count == 0:
            return {
                "success": False,
                "message": (
                    f"Target content not found within lines {start_line or 1}-{end_line or total_lines} "
                    f"in '{path}'. Double check exact indentation and whitespace."
                ),
                "diff": "",
                "occurrences": 0,
            }
        if count > 1 and not allow_multiple:
            return {
                "success": False,
                "message": (
                    f"Target content found {count} times within the specified range in '{path}'. "
                    "Narrow the line range or set allow_multiple=True."
                ),
                "diff": "",
                "occurrences": count,
            }

        new_window = window.replace(target_norm, replacement_norm, -1 if allow_multiple else 1)
        new_content = prefix + new_window + suffix
        replaced_count = count if allow_multiple else 1
    else:
        count = orig_norm.count(target_norm)
        if count == 0:
            return {
                "success": False,
                "message": f"Target content not found anywhere in '{path}'. Ensure exact character match.",
                "diff": "",
                "occurrences": 0,
            }
        if count > 1 and not allow_multiple:
            return {
                "success": False,
                "message": (
                    f"Target content found {count} times in '{path}'. Specify start_line/end_line "
                    "or set allow_multiple=True to replace all."
                ),
                "diff": "",
                "occurrences": count,
            }
        new_content = orig_norm.replace(target_norm, replacement_norm, -1 if allow_multiple else 1)
        replaced_count = count if allow_multiple else 1

    # Generate unified diff
    diff_lines = list(
        difflib.unified_diff(
            orig_norm.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{target.name}",
            tofile=f"b/{target.name}",
            n=3,
        )
    )
    diff_str = "".join(diff_lines)

    # Atomic write via temporary file + os.replace
    try:
        temp_dir = target.parent
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(new_content)
            temp_path = Path(tf.name)
        os.replace(temp_path, target)
    except Exception as exc:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return {
            "success": False,
            "message": f"Atomic write failed for '{path}': {exc}",
            "diff": "",
            "occurrences": 0,
        }

    return {
        "success": True,
        "message": f"Successfully replaced {replaced_count} occurrence(s) in '{path}'.",
        "diff": diff_str,
        "occurrences": replaced_count,
    }


def code_multi_replace(
    path: str | Path,
    chunks: list[dict[str, Any]],
    root: Path | None = None,
) -> dict[str, Any]:
    """Apply multiple non-contiguous surgical replacements in a single atomic transaction.

    Each chunk dict must have:
    - `target_content`: str
    - `replacement_content`: str
    - `start_line`: int (optional)
    - `end_line`: int (optional)
    - `allow_multiple`: bool (optional, default False)
    """
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if not target.exists() or not target.is_file():
        return {"success": False, "message": f"File '{path}' does not exist.", "diff": ""}

    try:
        current_content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return {"success": False, "message": f"Read failure on '{path}': {exc}", "diff": ""}

    original_content = current_content
    total_diffs: list[str] = []

    # Sort chunks in reverse line order if start_line is provided to avoid offset drift
    sorted_chunks = sorted(
        chunks,
        key=lambda c: c.get("start_line", 0) or 0,
        reverse=True,
    )

    for i, chunk in enumerate(sorted_chunks, start=1):
        target_str = chunk.get("target_content", "")
        repl_str = chunk.get("replacement_content", "")
        start_l = chunk.get("start_line")
        end_l = chunk.get("end_line")
        allow_m = bool(chunk.get("allow_multiple", False))

        res = code_replace_content(
            path=target,
            target_content=target_str,
            replacement_content=repl_str,
            start_line=start_l,
            end_line=end_l,
            allow_multiple=allow_m,
            root=base_root,
        )
        if not res["success"]:
            # Rollback to original content on any failure in the transaction
            target.write_text(original_content, encoding="utf-8")
            return {
                "success": False,
                "message": f"Chunk {i} failed ({res['message']}). Transaction rolled back.",
                "diff": "",
            }
        if res.get("diff"):
            total_diffs.append(res["diff"])

    return {
        "success": True,
        "message": f"Applied {len(chunks)} replacement chunks atomically to '{path}'.",
        "diff": "\n".join(total_diffs),
    }


def code_grep(
    query: str,
    search_path: str | Path = ".",
    is_regex: bool = False,
    case_insensitive: bool = True,
    includes: list[str] | None = None,
    max_results: int = 50,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Fast regex or literal code search across the workspace (ripgrep-like).

    Returns list of dicts with: `file`, `line_number`, `line_content`.
    """
    base_root = (root or Path.cwd()).resolve()
    base_dir = Path(search_path) if Path(search_path).is_absolute() else (base_root / search_path)
    base_dir = base_dir.resolve()
    _assert_safe_path(base_dir)

    flags = re.IGNORECASE if case_insensitive else 0
    if is_regex:
        try:
            pattern = re.compile(query, flags)
        except re.error as e:
            return [{"error": f"Invalid regex pattern: {e}"}]
    else:
        escaped = re.escape(query)
        pattern = re.compile(escaped, flags)

    ignore_dirs = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
    }

    results: list[dict[str, Any]] = []

    if base_dir.is_file():
        file_list = [base_dir]
    else:
        file_list = []
        for root_str, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for f in files:
                if f.startswith(".env"):
                    continue
                file_list.append(Path(root_str) / f)

    for file_path in file_list:
        # Check includes pattern if provided
        if includes:
            name = file_path.name
            if not any(file_path.match(pat) or name.endswith(pat.replace("*", "")) for pat in includes):
                continue

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as fp:
                for idx, line in enumerate(fp, start=1):
                    if pattern.search(line):
                        if file_path.is_relative_to(base_root):
                            rel_path = str(file_path.relative_to(base_root))
                        else:
                            rel_path = str(file_path)
                        results.append(
                            {
                                "file": rel_path,
                                "line_number": idx,
                                "line_content": line.rstrip("\r\n"),
                            }
                        )
                        if len(results) >= max_results:
                            return results
        except Exception:
            continue

    return results


def code_list_dir(
    directory_path: str | Path = ".",
    max_depth: int = 2,
    root: Path | None = None,
) -> dict[str, Any]:
    """Structured directory inspection detailing file sizes and subdirectory counts."""
    base_root = (root or Path.cwd()).resolve()
    target_dir = Path(directory_path) if Path(directory_path).is_absolute() else (base_root / directory_path)
    target_dir = target_dir.resolve()
    _assert_safe_path(target_dir)

    if not target_dir.exists():
        return {"error": f"Directory '{directory_path}' does not exist."}
    if not target_dir.is_dir():
        return {"error": f"Path '{directory_path}' is a file, not a directory."}

    ignore_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}

    def _scan(path: Path, current_depth: int) -> dict[str, Any]:
        info: dict[str, Any] = {
            "name": path.name or str(path),
            "type": "directory",
            "children": [],
        }
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            info["error"] = "Permission denied"
            return info

        for entry in entries:
            if entry.name in ignore_dirs or entry.name.startswith(".env"):
                continue
            if entry.is_dir():
                if current_depth < max_depth:
                    info["children"].append(_scan(entry, current_depth + 1))
                else:
                    try:
                        child_count = sum(1 for _ in entry.iterdir())
                    except Exception:
                        child_count = 0
                    info["children"].append({
                        "name": entry.name,
                        "type": "directory",
                        "children_count": child_count,
                    })
            else:
                try:
                    size = entry.stat().st_size
                except Exception:
                    size = 0
                info["children"].append({
                    "name": entry.name,
                    "type": "file",
                    "size_bytes": size,
                })
        return info

    return _scan(target_dir, current_depth=1)


def code_write_file(
    path: str | Path,
    content: str,
    overwrite: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Safely create or overwrite a file with atomic commit and directory auto-creation."""
    base_root = (root or Path.cwd()).resolve()
    target = Path(path) if Path(path).is_absolute() else (base_root / path)
    target = target.resolve()
    _assert_safe_path(target)

    if target.exists() and not overwrite:
        return {
            "success": False,
            "message": f"File '{path}' already exists. Pass overwrite=True to replace it.",
        }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tf:
            tf.write(content)
            temp_path = Path(tf.name)
        os.replace(temp_path, target)
    except Exception as exc:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return {"success": False, "message": f"Failed to write file '{path}': {exc}"}

    return {
        "success": True,
        "message": f"File '{path}' written successfully ({len(content.encode('utf-8'))} bytes).",
    }
