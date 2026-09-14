import sys
sys.path.insert(0, r"d:\WIS")
from abilities.registry import AbilityRegistry
import json

reg = AbilityRegistry.with_defaults()
schemas = reg.get_schemas()
print(json.dumps(schemas, indent=2))
