import sys
import os
import asyncio
from pathlib import Path

# Add project root
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from core.llm_client import LocalLLMClient

print("Creating LocalLLMClient...", flush=True)
client = LocalLLMClient()

print("Loading model...", flush=True)
model = client.load_model()
print("Model returned:", model, flush=True)

if model:
    print("Testing synchronous call...", flush=True)
    try:
        res = model("Hello, who are you?", max_new_tokens=20)
        print("Sync result:", res, flush=True)
    except Exception as e:
        print("Sync error:", type(e), e, flush=True)

    print("Testing client.generate async...", flush=True)
    try:
        async def run_gen():
            return await client.generate("Hello, who are you?", max_tokens=20)
        res_async = asyncio.run(run_gen())
        print("Async result:", res_async, flush=True)
    except Exception as e:
        print("Async error:", type(e), e, flush=True)
