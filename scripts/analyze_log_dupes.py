# -*- coding: utf-8 -*-
"""Segundo nivel: distingue repeticion IDENTICA de exploracion legitima.

Una racha de 39 `code_view_file` puede ser exploracion util (39 archivos
distintos) o un bucle inutil (el mismo archivo 39 veces). Hay que medirlo
antes de tocar nada.
"""
import io
import re
import sys
from collections import Counter

PATH = r"D:\WIS\logs\wis.log"

TOOL = re.compile(r"TOOL_CALL \| ([\w\.]+) \| params=(.*)$")
LOOP_DONE = re.compile(r"LOOP_DONE \| steps=(\d+)/(\d+)")

# Normaliza params: quita el ruido inyectado por el pipeline para comparar
# la intencion real de la llamada.
NOISE = re.compile(r'"_session_id": "[^"]*"|"_cancel_event": "[^"]*"')

records = []  # (tool, normalized_params)
with io.open(PATH, "r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        if "STREAM CHUNK" in line:
            continue
        m = TOOL.search(line)
        if m:
            tool = m.group(1)
            params = NOISE.sub("", m.group(2)).strip()
            # el log trunca a veces; comparamos lo que hay
            records.append((tool, params[:300]))

exact = Counter()
for rec in records:
    exact[rec] += 1

total = len(records)
distinct = len(exact)
redundant = total - distinct

print("=" * 70)
print("REPETICION IDENTICA (misma tool + mismos params) EN TODO EL LOG")
print("=" * 70)
print("Llamadas totales          : %d" % total)
print("Llamadas distintas        : %d" % distinct)
print("Repeticiones exactas      : %d  (%.0f%% del total)"
      % (redundant, 100.0 * redundant / max(total, 1)))

print("\n--- Top 15 llamadas repetidas EXACTAMENTE ---")
for (tool, params), n in exact.most_common(15):
    if n < 2:
        break
    print("   x%-4d %s" % (n, tool))
    print("          %s" % params[:110].replace("\n", " "))

# Cuantas de esas repeticiones son de tools de LECTURA (las que el pipeline
# exime de deduplicar via _is_repeatable_call)?
READ_RE = re.compile(
    r"^(?:code_|code_tools_)?(?:list|get|view|read|check|describe|grep|find|"
    r"search|inspect|probe|info|status|capture|detect|analyze|verify|health)",
    re.IGNORECASE,
)
read_dup = 0
write_dup = 0
for (tool, _params), n in exact.items():
    action = tool.split(".")[-1]
    if n < 2:
        continue
    if READ_RE.match(action):
        read_dup += n - 1
    else:
        write_dup += n - 1
print("\nRepeticiones evitables en tools de LECTURA : %d" % read_dup)
print("Repeticiones en tools de ACCION            : %d" % write_dup)

# Cuantas escrituras reales hubo durante todo el log?
writes = sum(n for (t, _), n in exact.items() if "write" in t or "replace" in t)
print("\nEscrituras reales (write/replace) en todo el log: %d" % writes)
print("Ratio lectura:escritura                          : %.1f : 1"
      % (total / max(writes, 1)))

sys.exit(0)
