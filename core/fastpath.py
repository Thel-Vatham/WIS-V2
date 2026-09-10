"""WIS Engineering Fast-Path Engine — v3.0.
===========================================
ARCHITECTURAL NOTE:
-------------------
FastPath does NOT contain hardcoded heuristics for ability dispatch.
The real "fastpath" for ability execution is SkillMemory: sequences that WIS
has already executed, verified, and synthesized through the ReAct loop become
instant 0ms cached executions without LLM involvement.

What FastPath DOES handle:
  - Pure Hardware Memory data queries (Device Graph, Pinout Maps, Procedural Memory)
    These are direct SQLite reads — no LLM needed, no execution side-effects.
  - Direct serial/MQTT dispatch ONLY when the payload is explicit and unambiguous
    (e.g. 'send "PING" to COM4') — these are transparent I/O, not reasoning tasks.

Everything else goes through the LLM ReAct loop → gets verified → gets synthesized
into SkillMemory → becomes instantaneous on future calls.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from core.hardware_memory import HardwareMemory

logger = logging.getLogger("wis.core.fastpath")


import unicodedata


def _normalize_text(text: str) -> str:
    try:
        nfkd = unicodedata.normalize("NFKD", text)
        ascii_text = nfkd.encode("ASCII", "ignore").decode("utf-8")
        return ascii_text.lower()
    except Exception:
        return text.lower()


class EngineeringFastPath:
    """Interceptor for pure data queries against Hardware Memory.

    Does NOT dispatch to abilities heuristically.
    Does NOT replace LLM reasoning with regex pattern matching.
    Only answers questions from local structured data (SQLite Device Graph).
    """

    def __init__(self, hardware_memory: HardwareMemory, abilities: Optional[Any] = None) -> None:
        self.hw_memory = hardware_memory
        self.abilities = abilities

    async def try_handle(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Resolves pure hardware data queries deterministically.
        Returns None if the request requires reasoning → falls through to LLM.
        """
        raw_text = (user_input or "").strip()
        if not raw_text:
            return None

        text = _normalize_text(raw_text)

        # ── 1. Device topology queries ────────────────────────────────────────
        # "list devices / hardware status / scan ports"
        if re.search(
            r"\b(list\s+(?:registered\s+)?devices?"
            r"|listar?\s+(?:dispositivos|puertos|hardware|devices|ports)"
            r"|estado\s+del?\s+hardware"
            r"|hardware\s+(?:status|topology|graph)"
            r"|scan\s+(?:ports|devices))\b",
            text,
        ):
            return self._query_device_list()

        # ── 2. Pinout / GPIO lookups ──────────────────────────────────────────
        # "pinout of ESP32 / what pin is SDA / where is servo connected"
        pin_match = re.search(
            r"(?:pinout\s+(?:of|for|de(?:l)?)\s+"
            r"|what\s+pin\s+(?:is|for|uses?)\s+"
            r"|que\s+pin\s+(?:usa|tiene|es)\s+"
            r"|pin\s+(?:map|mapping|for)\s+"
            r"|gpio\s+(?:map|for)\s+"
            r"|where\s+is\s+(?:the\s+)?)\s*([a-zA-Z0-9_\-]+)",
            text,
        )
        if pin_match:
            return self._query_pin(pin_match.group(1).strip())

        # ── 3. Procedural command memory lookup ───────────────────────────────
        # "how to compile for ESP32 / build command for arduino"
        proc_match = re.search(
            r"(?:how\s+to\s+(?:compile|flash|build|upload)"
            r"|build\s+command\s+(?:for|of)"
            r"|flash\s+command\s+(?:for|of)"
            r"|como\s+(?:se\s+)?(?:compila|flashea|construye)\s+"
            r"|comando\s+(?:de\s+)?(?:build|flash|compilacion)\s+(?:para|de))"
            r"\s+(?:the\s+)?(?:firmware\s+(?:of\s+)?)?([a-zA-Z0-9_\-]+)",
            text,
        )
        if proc_match:
            return self._query_proc_cmd(proc_match.group(1).strip())

        # ── 4. Direct serial send — explicit payload only ─────────────────────
        # "send 'PING' to COM4" — transparent I/O, no reasoning required
        direct_match = re.search(
            r"(?:send|write|transmit|envi?ar?|escribir?)\s+"
            r"[\"']([^\"']+)[\"']\s+"
            r"(?:to|via|through|a|por|en)\s+"
            r"([A-Za-z0-9]+)",
            raw_text,
            re.IGNORECASE,
        )
        if direct_match:
            payload = direct_match.group(1)
            port_or_dev = direct_match.group(2).strip().upper()
            return await self._dispatch_serial_send(payload, port_or_dev)

        # Everything else → LLM ReAct loop
        return None

    # ── Data query handlers ───────────────────────────────────────────────────

    def _query_device_list(self) -> Dict[str, Any]:
        devices = self.hw_memory.list_devices()
        if not devices:
            return self._result(
                "No hardware devices registered in the device graph. "
                "Use the hardware_memory ability to register devices.",
                [],
            )
        lines = [f"**Hardware Device Graph — {len(devices)} device(s):**"]
        for d in devices:
            lines.append(
                f"- **[{d['device_id'].upper()}]** {d['name']} | "
                f"Interface: `{d['interface']}` | Address: `{d['port_or_address']}` | "
                f"Baud: `{d['baud_rate']}` | Protocol: `{d['protocol']}` | Status: `{d['status']}`"
            )
        return self._result("\n".join(lines), [])

    def _query_pin(self, target: str) -> Optional[Dict[str, Any]]:
        # Search by device ID first
        pins = self.hw_memory.get_pin_map(target)
        if pins:
            lines = [f"**Pin Map for `{target.upper()}`:**"]
            for p in pins:
                lines.append(
                    f"- **{p['pin_or_gpio']}**: {p['label']} "
                    f"(Function: `{p['function']}`, Signal: `{p['signal_type']}`)"
                )
            return self._result("\n".join(lines), [])
        # Search by functional label (servo, motor, sda, scl, etc.)
        matches = self.hw_memory.find_pin_by_label(target)
        if matches:
            lines = [f"**Pins matching `{target}`:**"]
            for m in matches:
                lines.append(
                    f"- **{m['device_name']} ({m['device_id'].upper()})** → "
                    f"**{m['pin_or_gpio']}**: {m['label']} ({m['function']}) "
                    f"at `{m['port_or_address']}`"
                )
            return self._result("\n".join(lines), [])
        # Not found in device graph → let LLM handle (may use web search or knowledge)
        return None

    def _query_proc_cmd(self, context: str) -> Optional[Dict[str, Any]]:
        for tc in ("platformio", "arduino_cli", "idf", "esptool", "shell", "robotics_hal"):
            best = self.hw_memory.get_best_procedural_command(tc, context)
            if best:
                total = best["success_count"] + best["failure_count"]
                rate = round((best["success_count"] / max(1, total)) * 100, 1)
                return self._result(
                    f"**Memorized command for `{context}` [{tc}]:**\n"
                    f"```bash\n{best['command']}\n```\n"
                    f"*(Success rate: {rate}% over {best['success_count']} executions)*",
                    [],
                )
        return None

    # ── Direct I/O dispatch ───────────────────────────────────────────────────

    async def _dispatch_serial_send(self, payload: str, port_or_dev: str) -> Optional[Dict[str, Any]]:
        """Direct serial write — only when payload is explicit string literal."""
        ab = None
        if self.abilities is not None and hasattr(self.abilities, "get"):
            try:
                ab = self.abilities.get("serial_comm")
            except Exception:
                pass
        if ab and hasattr(ab, "execute"):
            try:
                res = await ab.execute("write", {"port": port_or_dev, "data": payload})
                msg = res.get("message") or ("Data sent." if res.get("success") else "Send failed.")
                return self._result(
                    f"**[SERIAL DIRECT → {port_or_dev}]** {msg}",
                    [{"action": "serial_comm.write", "params": {"port": port_or_dev, "data": payload}}],
                )
            except Exception as exc:
                logger.error("FastPath serial send error: %s", exc)
        # If ability unavailable, fall through to LLM
        return None

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _result(response: str, calls: list) -> Dict[str, Any]:
        return {
            "handled": True,
            "response": response,
            "calls": calls,
            "path_used": "fastpath",
            "success": True,
        }
