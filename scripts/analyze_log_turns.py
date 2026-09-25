# -*- coding: utf-8 -*-
"""Analiza wis.log: cuantifica pasos por turno y llamadas repetidas.

Objetivo: medir por que WIS gasta decenas de pasos sin cerrar el objetivo.
"""
import io
import re
import sys
from collections import Counter

PATH = r"D:\WIS\logs\wis.log"

STEP = re.compile(r"STEP \| (\d+)/(\d+)")
TOOL = re.compile(r"TOOL_CALL \| ([\w\.]+) \| params=(\{.*?\})(?= \| _session_id|$)")
RESP = re.compile(r"RESPONSE \| success=(\w+) \| path=(\w+) \| steps=(\d+)")
LOOPDONE = re.compile(r"LOOP_DONE \| steps=(\d+)/(\d+) \| success=(\w+)")
PROMISE = re.compile(r"turno cerrado en promesa")
NUDGE = re.compile(r"nudge (\d+)/(\d+)")

steps_per_turn = []
max_seen = 0
tool_seq = []          # secuencia global de (step, tool)
consecutive_dupes = 0
dupe_runs = []
promises = 0
nudges = 0
loop_done_success = Counter()
per_tool = Counter()

cur_step = 0
run_tool = None
run_len = 0


def flush_run():
    global run_tool, run_len
    if run_tool and run_len > 1:
        dupe_runs.append((run_tool, run_len))
    run_tool = None
    run_len = 0


with io.open(PATH, "r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        if "STREAM CHUNK" in line:
            continue
        m = STEP.search(line)
        if m:
            cur_step = int(m.group(1))
            max_seen = max(max_seen, cur_step)
            steps_per_turn.append(cur_step)
        m = TOOL.search(line)
        if m:
            tool = m.group(1)
            per_tool[tool] += 1
            if tool == run_tool:
                run_len += 1
            else:
                flush_run()
                run_tool = tool
                run_len = 1
        if PROMISE.search(line):
            promises += 1
        m = NUDGE.search(line)
        if m:
            nudges += 1
        m = LOOPDONE.search(line)
        if m:
            loop_done_success[m.group(3)] += 1

flush_run()

print("=" * 68)
print("ANALISIS DE wis.log")
print("=" * 68)
print("Paso maximo alcanzado en un turno : %d" % max_seen)
print("Eventos STEP registrados         : %d" % len(steps_per_turn))
print("Turnos cerrados en promesa       : %d" % promises)
print("Nudges anti-estancamiento        : %d" % nudges)
print("LOOP_DONE success                : %s" % dict(loop_done_success))

print("\n--- Llamadas repetidas CONSECUTIVAS (misma tool, sin otra en medio) ---")
if dupe_runs:
    total_wasted = sum(n - 1 for _, n in dupe_runs)
    print("Rachas detectadas: %d  |  llamadas redundantes: %d" % (len(dupe_runs), total_wasted))
    print("\nTop 20 rachas mas largas:")
    for tool, n in sorted(dupe_runs, key=lambda x: -x[1])[:20]:
        print("   %-38s x%d" % (tool, n))
else:
    print("(ninguna)")

print("\n--- Top 15 tools mas invocadas ---")
for tool, n in per_tool.most_common(15):
    print("   %-42s %d" % (tool, n))

# Distribucion de pasos por turno (los picos altos = desperdicio)
if steps_per_turn:
    print("\n--- Distribucion de pasos por turno ---")
    buckets = Counter()
    for s in steps_per_turn:
        if s <= 5:
            buckets["1-5"] += 1
        elif s <= 10:
            buckets["6-10"] += 1
        elif s <= 20:
            buckets["11-20"] += 1
        elif s <= 30:
            buckets["21-30"] += 1
        else:
            buckets["31+"] += 1
    for k in ("1-5", "6-10", "11-20", "21-30", "31+"):
        print("   %-6s %d" % (k, buckets[k]))

sys.exit(0)
