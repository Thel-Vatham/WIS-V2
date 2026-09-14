import sys
sys.path.insert(0, r"d:\WIS")
from main import _register_default_abilities
from abilities.registry import AbilityRegistry
import json

reg = AbilityRegistry()
_register_default_abilities(reg, {})
schemas = reg.get_schemas()
for s in schemas:
    print(f"Skill: {s['skill']} -> Actions: {[a['action'] for a in s['actions']]}")
