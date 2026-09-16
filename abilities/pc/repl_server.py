import sys
import json
import io
import traceback
import contextlib
import ast

def _run_with_implicit_print(code_str: str, global_env: dict):
    """Ejecuta código y si la última línea es una expresión, la imprime (como un REPL)."""
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        exec(code_str, global_env)
        return

    if not tree.body:
        return

    # Si la última instrucción es una expresión, la separamos
    last_node = tree.body[-1]
    if isinstance(last_node, ast.Expr):
        # Ejecutamos todo menos la última
        if len(tree.body) > 1:
            body_without_last = ast.Module(body=tree.body[:-1], type_ignores=[])
            exec(compile(body_without_last, filename="<ast>", mode="exec"), global_env)
        
        # Evaluamos y casteamos el resultado a string
        expr_val = eval(compile(ast.Expression(body=last_node.value), filename="<ast>", mode="eval"), global_env)
        if expr_val is not None:
            print(repr(expr_val))
    else:
        # Todo es script (ej. for loop, def, etc)
        exec(code_str, global_env)

def main():
    # Inicializa el entorno con un nombre amigable
    global_env = {"__name__": "__main__"}
    
    # Evita que el stdout original estropee nuestro canal JSON
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            req = json.loads(line)
            code_block = req.get("code", "")
            req_id = req.get("id", "unknown")
            
            output_io = io.StringIO()
            error_io = io.StringIO()
            
            with contextlib.redirect_stdout(output_io), contextlib.redirect_stderr(error_io):
                try:
                    _run_with_implicit_print(code_block, global_env)
                except Exception:
                    traceback.print_exc(file=error_io)
            
            result = {
                "id": req_id,
                "stdout": output_io.getvalue(),
                "stderr": error_io.getvalue()
            }
            # Escribir la respuesta JSON al stdout real
            original_stdout.write(json.dumps(result) + "\n")
            original_stdout.flush()
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            # Silently ignore format errors in stdin so the loop continues
            try:
                error_res = {"id": "error", "stdout": "", "stderr": f"REPL fatal error: {e}"}
                original_stdout.write(json.dumps(error_res) + "\n")
                original_stdout.flush()
            except Exception:
                pass

if __name__ == "__main__":
    main()
