"""
WIS Swarm Telepathy Ability.
============================
Habilidad para comunicación inter-agentes (Enjambre/Swarm).
Permite a una instancia de WIS enviar conocimientos y descubrimientos
a otras instancias (consolas/procesos paralelos) de forma asíncrona.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from abilities.base import Ability
from core.event_bus import event_bus

logger = logging.getLogger("wis.abilities.telepathy")

class SwarmTelepathyAbility(Ability):
    """Motor de telepatía para enjambre multi-agente."""

    @property
    def name(self) -> str:
        return "telepathy"

    @property
    def description(self) -> str:
        return (
            "Permite comunicación telepática (Swarm Event Bus) con otras instancias de WIS paralelas. "
            "Úsalo para hacer 'broadcast' de conocimientos críticos (ej. puertos, contraseñas, estados) "
            "que otras consolas necesiten saber sin interrumpirlas."
        )

    @property
    def domain(self) -> str:
        return "system"

    def get_schema(self) -> list:
        return [
            {
                "action": "broadcast_knowledge",
                "description": "Publica un descubrimiento crítico para que todos los demás agentes de WIS lo asimilen en su memoria.",
                "params": {
                    "topic": "str - Tema del conocimiento (ej. 'Planta Helada - Base de datos')",
                    "message": "str - El conocimiento o instrucción a compartir."
                }
            }
        ]

    async def execute(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        
        if action == "broadcast_knowledge":
            topic = params.get("topic", "General")
            message = params.get("message", "")
            
            if not message:
                return {"success": False, "error": "El mensaje telepático no puede estar vacío."}
            
            # Emitimos el evento telepático al event_bus compartido
            payload = {
                "topic": topic,
                "message": message
            }
            event_bus.emit("swarm.broadcast", payload)
            
            return {
                "success": True,
                "message": f"Conocimiento telepático sobre '{topic}' transmitido al enjambre."
            }

        return {"success": False, "error": f"Acción desconocida: {action}"}
