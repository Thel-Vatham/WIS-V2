"""
Guard: the previously-orphaned subagent/orchestration abilities are real,
importable, and register cleanly (prevents them drifting back to dead code).
"""
from __future__ import annotations

import importlib

from abilities.registry import AbilityRegistry
from core.skill_inventory import SkillInventory, collect_registered

SUBAGENT_MODULES = [
    ("abilities.dev_agent", "DevAgent"),
    ("abilities.pc_agent", "PCAgent"),
    ("abilities.research_agent", "ResearchAgent"),
    ("abilities.runtime_manager", "RuntimeManager"),
    ("abilities.antigravity_tools", "AntigravityToolsAbility"),
    ("abilities.telepathy", "SwarmTelepathyAbility"),
    ("abilities.cron", "CronAbility"),
    ("abilities.mcp", "MCPAbility"),
    ("abilities.swarm", "SwarmAbility"),
    ("abilities.background", "BackgroundAbility"),
]


def test_all_subagent_abilities_import_and_have_schemas():
    for mod_name, cls_name in SUBAGENT_MODULES:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name)
        inst = cls()
        assert inst.name, f"{cls_name} has no name"
        assert inst.get_schema(), f"{cls_name} has empty schema"


def test_full_registry_has_no_missing_pillar_tools(temp_db_path):
    """Once subagents are wired, the 'piel' (3 pillars) validates with zero gaps."""
    registry = AbilityRegistry.with_defaults()
    registered = collect_registered(registry)
    # Subagent actions that the pillars depend on must now be present.
    for expected in (
        "dev_agent.edit_file",
        "dev_agent.run_tests",
        "pc_agent.run_command",
        "research_agent.deep_search",
    ):
        assert expected in registered, f"{expected} missing from registry"

    skin = SkillInventory(db_path=temp_db_path)
    missing = skin.sync(registered)
    assert missing == {}, f"piel has gaps: {missing}"
    skin.close()
