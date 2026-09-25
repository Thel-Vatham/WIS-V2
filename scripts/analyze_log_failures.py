# -*- coding: utf-8 -*-
"""Agrupa los fallos de wis.log para ver QUE bloquea a WIS sistematicamente.

Si una tool falla siempre con el mismo error, el agente no puede completar el
objetivo por mucho que itere: no es un problema de pasos, es una tool rota.
"""
import io
import re
import sys
from collections import Counter, defaultdict

PATH = r"D:\WIS\logs\wis.log"

TRACE_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[(\w+)\]")
TOOL_RESULT = re.compile(r"TOOL_RESULT \| (\w+) \| ([\w\.]+) \|")
ERROR_LINE = re.compile(r"\[(ERROR|CRITICAL)\] ([\w\.]+): (.*)$")

fail_by_tool = Counter()
ok_by_tool = Counter()
err_msgs = Counter()
err_by_logger = Counter()
tracebacks = 0

# firma del error: normaliza numeros/paths para agrupar
NUM = re.compile(r"\d+")
PATH_RE = re.compile(r"[A-Za-z]:\\\\?[^\s\"']+|/[\w/\.\-]+")


def signature(msg):
    m = NUM.sub("N", msg)
    m = PATH_RE.sub("<path>", m)
    return m[:190]


context = []  # ventana de lineas para atribuir trazas a su tool
with io.open(PATH, "r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        if "STREAM CHUNK" in line:
            continue
        m = TOOL_RESULT.search(line)
        if m:
            status, tool = m.group(1), m.group(2)
            if status.upper() == "SUCCESS":
                ok_by_tool[tool] += 1
            else:
                fail_by_tool[tool] += 1
        if "Traceback (most recent call last)" in line:
            tracebacks += 1
        m = ERROR_LINE.search(line)
        if m:
            level, logger_name, msg = m.groups()
            err_by_logger[logger_name] += 1
            key = signature(msg.strip())
            if key:
                err_msgs[key] += 1

print("=" * 72)
print("ANALISIS DE FALLOS")
print("=" * 72)
print("Tracebacks en el log : %d" % tracebacks)
print("Lineas ERROR/CRITICAL: %d" % sum(err_by_logger.values()))

print("\n--- Tools con MAS fallos registrados ---")
all_tools = set(fail_by_tool) | set(ok_by_tool)
rows = []
for t in all_tools:
    f = fail_by_tool.get(t, 0)
    o = ok_by_tool.get(t, 0)
    tot = f + o
    if tot:
        rows.append((f, o, tot, t))
rows.sort(reverse=True)
print("  %-40s %5s %5s %7s" % ("tool", "fail", "ok", "fail%"))
for f, o, tot, t in rows[:18]:
    print("  %-40s %5d %5d %6.0f%%" % (t, f, o, 100.0 * f / tot))

print("\n--- Top 12 mensajes de ERROR (agrupados) ---")
for msg, n in err_msgs.most_common(12):
    print("  x%-4d %s" % (n, msg))

print("\n--- ERROR por modulo emisor ---")
for name, n in err_by_logger.most_common(12):
    print("  x%-4d %s" % (n, name))

sys.exit(0)
