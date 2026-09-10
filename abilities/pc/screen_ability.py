"""
WIS Screen Ability.
Wraps AVRORA's SOM (Set of Marks) vision engine and screen tools.
"""
from __future__ import annotations

import os
from typing import Any
from abilities.base import Ability

from .som import ScreenMarker
from .screen_vision import ScreenVisionOps

class ScreenAbility(Ability):
    def __init__(self):
        self.vision = ScreenVisionOps()
        self.marker = ScreenMarker()

    @property
    def name(self) -> str:
        return "screen_vision"

    @property
    def description(self) -> str:
        return "Capture screen, find UI elements, and draw Set-of-Marks on the screen."

    @property
    def domain(self) -> str:
        return "pc"

    def get_schema(self) -> list:
        return [
            {
                "action": "capture_screen",
                "description": "Capture screen and optionally annotate UI elements.",
                "params": {"annotate": "Boolean to draw marks"}
            },
            {
                "action": "find_element",
                "description": "Find an element by text on the screen.",
                "params": {"text": "Text to search for"}
            }
        ]

    async def execute(self, action: str, params: dict) -> dict:
        try:
            if action == "capture_screen":
                annotate = params.get("annotate", False)
                if annotate:
                    path, marks = self.marker.annotate_screen()
                    return {"success": True, "data": {"path": str(path), "marks": marks}, "message": "Annotated screen captured"}
                else:
                    path = self.vision.capture_screen()
                    return {"success": True, "data": str(path), "message": "Screen captured"}
                    
            elif action == "find_element":
                text = params.get("text", "")
                result = self.vision.find_text(text)
                return {"success": bool(result), "data": result, "message": f"Found '{text}'" if result else "Not found"}
                
            return {"success": False, "message": f"Unknown action: {action}"}
            
        except Exception as e:
            return {"success": False, "message": str(e)}
