"""Skill Inventory: WIS's always-on core pillars ("la piel").

Ported from AVRORA's ``core/skills/inventory.py``. WIS always carries three
innate capabilities that are NEVER injected away, regardless of which tool
schemas happen to be passed for function calling:

1. ``pc``   — control the PC natively (files, shell, processes, terminals, GUI).
2. ``web``  — browse and search the web autonomously and report.
3. ``code`` — write, edit, run and verify code (surgical tools, TDD, dev agent).

This module:

1. Declares the pillars as a SINGLE source of truth (no scattered hardcoding),
   mapped to WIS's real ``skill.action`` identifiers.
2. PERSISTS them to SQLite (``skill_inventory``) so they survive restarts.
3. VALIDATES them against the live registry — a declared tool that is not
   registered is reported honestly (never a phantom claim).
4. INJECTS them into every system prompt ("la piel") so the model ALWAYS knows
   its three pillars.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

# The three innate pillars -> WIS ``skill.action`` identifiers (single source
# of truth). Each string is ``ability_name.action_name``.
CORE_PILLARS: dict[str, dict[str, Any]] = {
    "pc": {
        "description": "Control the PC natively: files, shell, processes, persistent terminals, GUI and system info.",
        "tools": [
            "system.execute_shell",
            "system.get_system_info",
            "system.get_process_list",
            "system.open_application",
            "file_manager.read_file",
            "file_manager.write_file",
            "file_manager.list_directory",
            "persistent_terminal.terminal_create",
            "persistent_terminal.terminal_send",
            "persistent_terminal.terminal_read",
            "pc_agent.run_command",
            "pc_agent.open_app",
        ],
    },
    "web": {
        "description": "Browse and search the web autonomously and report.",
        "tools": [
            "web_search.search",
            "knowledge.web_search",
            "browser.goto",
            "browser.observe",
            "research_agent.deep_search",
            "research_agent.browse_and_extract",
            "research_agent.fetch_page",
        ],
    },
    "code": {
        "description": "Write, edit, run and verify code on the real workspace (surgical tools, TDD, dev agent).",
        "tools": [
            "code_tools.code_view_file",
            "code_tools.code_grep",
            "code_tools.code_replace_content",
            "code_tools.code_multi_replace",
            "code_tools.code_write_file",
            "code_tools.code_list_dir",
            "code_tools.run_python",
            "code_tools.ast_inspect_symbols",
            "code_tools.ast_rename_symbol",
            "code_tools.tdd_cycle",
            "dev_agent.edit_file",
            "dev_agent.view_file",
            "dev_agent.run_tests",
            "dev_agent.shell",
            "dev_agent.create_project",
            "dev_agent.map_architecture",
        ],
    },
}


def collect_registered(registry: Any) -> list[str]:
    """Build the set of registered ``skill.action`` identifiers from a registry.

    Accepts any object exposing ``all() -> dict[str, Ability]`` (e.g.
    ``AbilityRegistry``). Returns a flat list of ``ability.action`` strings.
    """
    ids: list[str] = []
    for name, ability in registry.all().items():
        for entry in ability.get_schema():
            if isinstance(entry, dict):
                action = entry.get("action")
                if action:
                    ids.append(f"{name}.{action}")
    return ids


class SkillInventory:
    """Persisted, validated record of the core pillars ("la piel")."""

    def __init__(self, db_path: Any) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._sync_stamp = 0.0

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_inventory(
                pillar TEXT PRIMARY KEY,
                description TEXT,
                tools TEXT,
                updated_at REAL
            )
            """
        )
        self._conn.commit()

    def sync(self, registered: list[str] | tuple[str, ...] | set[str]) -> dict[str, list[str]]:
        """Persist the declared pillars; return the tools NOT registered.

        Honest validation: a declared tool missing from the live registry is
        reported (never silently claimed). The caller decides how to surface it
        (e.g. a warning log).
        """
        registered_set = {str(t) for t in registered}
        missing: dict[str, list[str]] = {}
        now = time.time()
        for pillar, spec in CORE_PILLARS.items():
            not_registered = [t for t in spec["tools"] if t not in registered_set]
            if not_registered:
                missing[pillar] = not_registered
            self._conn.execute(
                "INSERT INTO skill_inventory(pillar, description, tools, updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(pillar) DO UPDATE SET "
                "description=excluded.description, tools=excluded.tools, updated_at=excluded.updated_at",
                (pillar, spec["description"], json.dumps(spec["tools"]), now),
            )
        self._conn.commit()
        self._sync_stamp = now
        return missing

    def pillars(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT pillar FROM skill_inventory ORDER BY pillar"
        ).fetchall()
        return [r["pillar"] for r in rows]

    def text(self) -> str:
        """Render the "piel" block injected into every system prompt."""
        rows = self._conn.execute(
            "SELECT pillar, description, tools FROM skill_inventory ORDER BY pillar"
        ).fetchall()
        if not rows:
            return "(none recorded)"
        lines: list[str] = [
            "CORE CAPABILITIES (always available — never assume these are missing):"
        ]
        for r in rows:
            tools = ", ".join(json.loads(r["tools"]))
            lines.append(f"- {r['pillar']}: {r['description']}  [tools: {tools}]")
        return "\n".join(lines)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
