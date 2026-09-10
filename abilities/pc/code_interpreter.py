"""Python Code Interpreter (REPL) Agent Tool.

Permite que el modelo LLM, especialmente los modelos pequeños entrenados para código,
ejecuten bloques de Python de forma local para interactuar con el sistema operativo sin
necesidad de formatear esquemas complejos de JSON Tools.
"""
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

def run_python_code(code: str, timeout: int = 60) -> str:
    """Ejecuta código Python arbitrario en un entorno local y devuelve el resultado.
    
    Ideal para manipulación de archivos, requests de sistema o control de GUI
    usando librerías estándar.
    """
    if not code or not code.strip():
        return "Error: No code provided."

    # Remover backticks markdown si el LLM los incluye
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    elif code.startswith("```"):
        code = code[len("```"):].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    # Prevenir bucles infinitos peligrosos básicos o comandos destructivos directos si se quiere, 
    # aunque confiamos en el entorno local del usuario.
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        temp_path = f.name

    try:
        # Ejecutamos el intérprete actual para mantener compatibilidad con las librerías del entorno
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        
        output = []
        if result.stdout:
            output.append("STDOUT:\n" + result.stdout)
        if result.stderr:
            output.append("STDERR:\n" + result.stderr)
            
        if not output:
            if result.returncode == 0:
                return "Ejecución completada sin salida en consola."
            else:
                return f"El script finalizó con código de error {result.returncode}."
                
        return "\n".join(output)
        
    except subprocess.TimeoutExpired:
        return f"Error: El código excedió el tiempo límite de {timeout} segundos y fue abortado."
    except Exception as e:
        logger.error(f"Failed to execute python code: {e}")
        return f"Error interno al ejecutar código: {e}"
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

# Exposición de la herramienta para el framework de Avrora
CODE_INTERPRETER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pc_run_python_code",
        "description": "Ejecuta un script de Python de forma local. Úsalo para manipular archivos, interactuar con el sistema operativo o automatizar tareas complejas. Retorna el stdout y stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "El código Python a ejecutar. Puede incluir múltiples líneas, imports y lógica completa."
                }
            },
            "required": ["code"],
            "additionalProperties": False
        }
    }
}
