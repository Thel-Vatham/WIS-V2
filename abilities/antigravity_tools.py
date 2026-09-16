"""
Antigravity Tools for WIS
Proporciona capacidades avanzadas de agente desarrollador, como
la edicion quirurgica de archivos y ejecucion robusta de comandos.
"""
import logging
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Dict, Any

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.antigravity_tools")

class AntigravityToolsAbility(Ability):
    @property
    def name(self) -> str:
        return "antigravity_tools"

    @property
    def description(self) -> str:
        return (
            "Herramientas avanzadas de desarrollo (estilo Antigravity) para WIS.\n"
            "Usa 'replace_file_content' para hacer modificaciones quirurgicas a archivos existentes sin tener que reescribirlos por completo.\n"
            "Usa 'run_command' para ejecutar comandos de terminal y compilar codigo."
        )

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "replace_file_content",
                "description": "Edita un bloque de codigo especifico en un archivo. Es vital usar esto en vez de reescribir todo el archivo.",
                "params": {
                    "path": "Ruta absoluta o relativa del archivo.",
                    "target_content": "El bloque exacto de codigo que deseas reemplazar. Debe coincidir caracter por caracter.",
                    "replacement_content": "El nuevo bloque de codigo que tomara su lugar."
                }
            },
            {
                "action": "run_command",
                "description": "Ejecuta un comando de consola (shell) y devuelve la salida.",
                "params": {
                    "command": "Comando a ejecutar.",
                    "timeout": "Tiempo maximo en segundos (opcional, por defecto 30)."
                }
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        action = (action or "").lower().strip()
        if action == "replace_file_content":
            return await asyncio.to_thread(self._replace_content, params)
        if action == "run_command":
            return await self._run_command(params)
        
        return {"success": False, "message": f"Accion '{action}' desconocida."}

    def _replace_content(self, params: dict) -> dict:
        path = params.get("path")
        target = params.get("target_content")
        replacement = params.get("replacement_content")
        
        if not all([path, target, replacement]):
            return {"success": False, "message": "Faltan parametros (path, target_content, replacement_content)."}
        
        file_path = Path(path).resolve()
        if not file_path.exists():
            return {"success": False, "message": f"El archivo no existe: {file_path}"}
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if target not in content:
                return {"success": False, "message": "El target_content no se encontro exactamente en el archivo."}
                
            new_content = content.replace(target, replacement)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            return {"success": True, "message": f"Archivo {file_path} editado quirurgicamente con exito."}
        except Exception as e:
            return {"success": False, "message": f"Error editando archivo: {e}"}

    async def _run_command(self, params: dict) -> dict:
        command = params.get("command")
        if not command:
            return {"success": False, "message": "Falta parametro 'command'."}
            
        timeout = int(params.get("timeout", 30))
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return {"success": False, "message": f"Comando excedio el timeout de {timeout}s"}
                
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            
            return {
                "success": process.returncode == 0,
                "stdout": out_str,
                "stderr": err_str,
                "returncode": process.returncode
            }
        except Exception as e:
            return {"success": False, "message": f"Error ejecutando comando: {e}"}
