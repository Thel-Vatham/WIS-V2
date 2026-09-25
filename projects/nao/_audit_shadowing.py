# -*- coding: utf-8 -*-
"""Auditoria AST del bridge NAO: detecta atributos de instancia que
sombrean metodos de la clase (shadowing) -> 'object is not callable'.
Es un analisis estatico: no necesita pynaoqi ni Python 2.
"""
import ast
import os
import sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nao_bridge.py")

with open(PATH, "r", encoding="utf-8") as fh:
    tree = ast.parse(fh.read(), PATH)

problems = []
for node in ast.walk(tree):
    if not isinstance(node, ast.ClassDef):
        continue
    methods = {
        n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # atributos asignados a self.<x> dentro de metodos de la clase
    attrs = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                if (
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "self"
                ):
                    attrs.setdefault(t.attr, sub.lineno)
    for name, lineno in sorted(attrs.items()):
        if name in methods:
            problems.append((node.name, name, lineno, "self.%s = ..." % name))

print("=" * 70)
print("AUDITORIA DE SHADOWING: %s" % PATH)
print("=" * 70)

# Ademas: usa self.<proxy> como callable en el dispatch?
src = open(PATH, "r", encoding="utf-8").read()
calls = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "nao"
        ):
            calls.append((f.attr, node.lineno))

if problems:
    print("\n[BUG] Atributos de instancia que SOMBREAN metodos de la clase:\n")
    for cls, name, lineno, expr in problems:
        print("  clase %s -> metodo '%s()' queda inalcanzable" % (cls, name))
        print("     porque en la linea %d se hace: %s" % (lineno, expr))
        for cname, cline in calls:
            if cname == name:
                print("     y el dispatch lo invoca en la linea %d: nao.%s(...)"
                      % (cline, cname))
        print("     -> TypeError: object is not callable\n")
else:
    print("\nOK: sin shadowing de metodos por atributos de instancia.\n")

print("Llamadas del dispatch (nao.<metodo>): %d" % len(calls))
sys.exit(1 if problems else 0)
