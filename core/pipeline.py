"""WIS Action Pipeline v3.0 — Pure-LLM Agentic ReAct loop.

Cognitive architecture (AVRORA philosophy):
  - NO hardcoded heuristics, regex fastpaths, or shortcuts.
  - EVERY initial user query goes directly to the LLM ReAct loop:
      think → parallel execute → empirical verify → metacognitive check
      → auto-repair → synthesize → cache in SkillMemory.
  - The ONLY fast execution is SkillMemory (proven+verified sequences).
    Speed is earned dynamically through synthesis, never hardcoded.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union

from core.safety import SafetyPolicy, FailureClassifier
from core.reasoning import ReasoningEngine
from core.event_bus import event_bus
from core.skill_memory import SkillMemory
from core.goal_manager import GoalManager
from core.verifier import MetacognitiveVerifier

logger = logging.getLogger("wis.core.pipeline")

PATH_KNOWN = "known"
PATH_NEW = "new"

DEFAULT_MAX_STEPS = 10
STEP_TIMEOUT_S = 60

AbilityFn = Callable[[Dict[str, Any]], Any]


class ActionPipeline:
    """Pipeline de accion puramente agentico con razonamiento LLM y SkillMemory."""

    def __init__(
        self,
        reasoning: ReasoningEngine,
        skill_memory: SkillMemory,
        abilities: Optional[Union[Dict[str, AbilityFn], Any]] = None,
        safety: Optional[SafetyPolicy] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        fastpath: Optional[Any] = None,
        hardware_memory: Optional[Any] = None,
    ) -> None:
        self.reasoning: ReasoningEngine = reasoning
        self.skill_memory: SkillMemory = skill_memory
        self.fastpath = None  # Deprecated & bypassed: 100% LLM driven
        self.hardware_memory = hardware_memory
        if isinstance(abilities, dict):
            self.abilities: Any = dict(abilities)
        elif abilities is not None:
            self.abilities = abilities
        else:
            self.abilities = {}
        self.safety: SafetyPolicy = safety or SafetyPolicy()
        self.max_steps: int = max(1, int(max_steps or DEFAULT_MAX_STEPS))

        # Goal Manager integration (set externally)
        self.goal_manager: Optional[GoalManager] = None

        # Approval mechanism for secure mode
        self._approval_event: Optional[asyncio.Event] = None
        self._approval_result: bool = False
        self._cancel_event: Optional[asyncio.Event] = None

        self._reflex_table: Dict[str, str] = {
            "hi": "Hello.",
            "hello": "Hello.",
            "hey": "Hello.",
            "hola": "Hello.",
            "buenas": "Good morning.",
            "buena": "Good morning.",
            "buenas dias": "Good morning.",
            "buenos dias": "Good morning.",
            "buenas tardes": "Good afternoon.",
            "buenas noches": "Good night.",
            "que tal": "Hello! How can I help you?",
            "como estas": "I'm doing great, thanks for asking! How can I help?",
            "thanks": "You're welcome.",
            "gracias": "You're welcome.",
            "bye": "Goodbye.",
            "adios": "Goodbye.",
            "chao": "Goodbye.",
            "hasta luego": "Goodbye.",
        }

    def register_ability(self, name: str, fn: AbilityFn) -> None:
        if isinstance(self.abilities, dict):
            self.abilities[name] = fn

    def register_reflex(self, trigger: str, response: str) -> None:
        key = (trigger or "").strip().lower()
        if key:
            self._reflex_table[key] = str(response or "")

    # ---- Approval API (called from server.py) -----------------------------

    def approve_action(self) -> None:
        """Aprueba la accion riesgosa en espera."""
        self._approval_result = True
        if self._approval_event:
            self._approval_event.set()

    def deny_action(self) -> None:
        """Deniega la accion riesgosa."""
        self._approval_result = False
        if self._approval_event:
            self._approval_event.set()

    def cancel_processing(self) -> None:
        """Cancela el loop agentico actual."""
        if self._cancel_event:
            self._cancel_event.set()

    # ---- Main Process -----------------------------------------------------

    async def process(
        self,
        text: str,
        sensor_data: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {
                "response": "",
                "calls": [],
                "results": [],
                "path_used": PATH_NEW,
                "success": True,
            }

        if tools is None and self.abilities:
            if hasattr(self.abilities, "get_schemas"):
                tools = self.abilities.get_schemas()

        event_bus.emit("pipeline.input_received", {"text": text})
        self._cancel_event = asyncio.Event()

        # --- Path: Known (SkillMemory cache) ---
        # ONLY previously proven, tested, and synthesized skills are replayed.
        result = self._try_known(text)
        if result is not None:
            event_bus.emit("pipeline.known_hit", {"text": text[:80]})
            event_bus.emit("pipeline.path_start", {"path": PATH_KNOWN, "text": text[:80]})
            calls = result.get("calls", [])
            results, ok = await self._execute_calls(calls)
            response = result.get("response", "")
            if ok:
                self.skill_memory.record_success(text, calls, response)
            else:
                self.skill_memory.record_failure(text, calls)
                event_bus.emit("pipeline.known_failed_fallback", {"text": text[:80]})
                new_result = await self._try_new(text, sensor_data, tools)
                return self._finalize(new_result, PATH_NEW, success=new_result["success"])
            final = {
                "response": response,
                "calls": calls,
                "results": results,
                "success": ok,
            }
            return self._finalize(final, PATH_KNOWN, success=ok)

        # --- Path: Pure-LLM ReAct Loop (ALL new tasks go directly to LLM) ---
        event_bus.emit("pipeline.new_path", {"text": text[:80]})
        event_bus.emit("pipeline.path_start", {"path": PATH_NEW, "text": text[:80]})
        result = await self._try_new(text, sensor_data, tools)
        return self._finalize(result, PATH_NEW, success=result["success"])

    # ---- Reflexive & Known -------------------------------------------------

    async def _try_reflexive(self, text: str) -> Optional[Dict[str, Any]]:
        normalized = text.strip().lower()
        if not normalized:
            return None

        normalized = re.sub(r"[?!.,]+$", "", normalized).strip()

        if normalized in self._reflex_table:
            return {
                "response": self._reflex_table[normalized],
                "calls": [],
                "results": [],
            }

        if normalized in ("who are you", "quien eres", "quien sos", "tu nombre"):
            name = self.reasoning.identity.get_name()
            desc = self.reasoning.identity.get_description()
            return {
                "response": f"I am {name}. {desc}",
                "calls": [],
                "results": [],
            }



        if any(h in normalized for h in ("que hora es", "dime la hora", "dime hora actual")):
            return {
                "response": "Checking current time...",
                "calls": [{"action": "get_current_time"}],
                "results": [],
            }

        if any(h in normalized for h in ("estado del sistema", "system info", "informacion del sistema", "como esta el sistema")):
            return {
                "response": "Checking system metrics...",
                "calls": [{"action": "get_system_info"}],
                "results": [],
            }

        # Semantic Intent Classifier using LocalLLMClient
        return await self._fast_intent_classification(text)

    async def _fast_intent_classification(self, text: str) -> Optional[Dict[str, Any]]:
        """Embedding-based intent classifier — no LLM, ~3ms, purely local.

        Uses cosine similarity against pre-defined intent anchor phrases via
        the same fastembed model used by SkillMemory. Falls through to LLM
        ReAct loop if no confident match (threshold 0.82).
        """
        try:
            from core.memory import _Embedder, _cosine_similarity
            embedder = _Embedder()

            # Intent anchors — minimal set for truly reflexive queries only.
            # Anything that requires reasoning goes straight to LLM.
            INTENT_ANCHORS: Dict[str, List[str]] = {
                "time": [
                    "what time is it", "current time", "que hora es",
                    "tell me the time", "dime la hora", "hora actual",
                ],
                "identity": [
                    "who are you", "what are you", "quien eres",
                    "introduce yourself", "your name",
                ],
                "open_app": [
                    "open application", "launch program", "abre la aplicacion",
                    "inicia el programa", "ejecuta la app", "start app"
                ],
            }

            query_vec = embedder.embed(text)
            best_intent: Optional[str] = None
            best_score: float = 0.0

            for intent, anchors in INTENT_ANCHORS.items():
                for anchor in anchors:
                    anchor_vec = embedder.embed(anchor)
                    score = _cosine_similarity(query_vec, anchor_vec)
                    if score > best_score:
                        best_score = score
                        best_intent = intent

            # High threshold — only intercept if very confident it's trivial
            if best_intent and best_score >= 0.82:
                if best_intent == "time":
                    return {
                        "response": "Checking current time...",
                        "calls": [{"action": "get_current_time"}],
                        "results": [],
                    }
                if best_intent == "identity":
                    name = self.reasoning.identity.get_name()
                    desc = self.reasoning.identity.get_description()
                    return {
                        "response": f"I am {name}. {desc}",
                        "calls": [],
                        "results": [],
                    }
                if best_intent == "open_app":
                    import os
                    known_apps = [
                        "chrome", "brave", "opera", "edge", "notepad", "calculator", "calc",
                        "word", "excel", "powerpoint", "winword", "powerpnt", "code", "vs code",
                        "spotify", "cmd", "powershell", "terminal", "paint", "mspaint"
                    ]
                    text_lower = text.lower()
                    target_app = None
                    for app in known_apps:
                        if app in text_lower:
                            target_app = app
                            break
                    if target_app:
                        return {
                            "response": f"Opening {target_app}...",
                            "calls": [{"action": "open_application", "app_name": target_app}],
                            "results": [],
                        }

        except Exception as e:
            logger.debug(f"pipeline: embedding classifier skipped: {e}")

        # Anything else → LLM ReAct loop
        return None

    @staticmethod
    def _compose_result_response(
        placeholder: str,
        calls: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
    ) -> str:
        """Compone la respuesta final con datos REALES de las tool calls reflejas.

        Antes de esta correccion, el placeholder ("Checking current time...")
        se devolvia como respuesta final aunque la herramienta ya hubiera
        devuelto el resultado (ej. la hora actual).
        """
        if not results:
            return placeholder

        lines: List[str] = []
        for call, res in zip(calls, results):
            action = str(call.get("action") or "").lower()
            output = res.get("output") or {}
            ok = bool(res.get("ok", False))

            if isinstance(output, dict):
                data = output.get("data") or {}
                message = output.get("message") or ""
            else:
                data, message = {}, str(output or "")

            if not ok:
                reason = (
                    res.get("reason")
                    or (output.get("message") if isinstance(output, dict) else None)
                    or (output.get("error") if isinstance(output, dict) else None)
                    or "unknown error"
                )
                lines.append(f"I couldn't complete that: {reason}")
                continue

            if action in ("time", "get_current_time"):
                t = data.get("time") if isinstance(data, dict) else None
                lines.append(f"The current time is {t}." if t else message)
            elif action in ("date", "get_current_date"):
                lines.append(message or (str(data) if data else placeholder))
            elif action in ("info", "get_system_info"):
                lines.append(message or (str(data) if data else placeholder))
            elif action in ("open_application", "launch", "execute"):
                params = call.get("params") if isinstance(call.get("params"), dict) else {}
                app = (
                    call.get("app_name")
                    or call.get("application")
                    or params.get("app_name")
                    or params.get("application")
                    or "application"
                )
                lines.append(f"Done. {app} launched successfully.")
            else:
                lines.append(message or placeholder)

        return " ".join(line for line in lines if line) or placeholder

    def _try_known(self, text: str) -> Optional[Dict[str, Any]]:
        skill = self.skill_memory.lookup(text)
        if not skill:
            return None
        return {
            "response": skill.get("response", ""),
            "calls": skill.get("calls", []),
            "results": [],
        }

    # ---- Multi-Step Agentic Loop -------------------------------------------

    async def _try_new(
        self,
        text: str,
        sensor_data: Optional[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Full-agentic ReAct loop: think → parallel execute → verify → metacognitive check → repair → synthesize."""
        all_calls = []
        all_results = []
        text_response = ""
        final_ok = True
        trace: list = []  # Structured JSON trace
        step_count = 0
        _verifier = MetacognitiveVerifier()

        for step in range(1, self.max_steps + 1):
            step_count = step

            # Check cancellation
            if self._cancel_event and self._cancel_event.is_set():
                event_bus.emit("pipeline.loop_cancelled", {"step": step, "text": text[:80]})
                break

            event_bus.emit("pipeline.loop_step", {
                "step": step, "max_steps": self.max_steps,
                "text": text[:80],
            })

            # Build prompt with accumulated context
            if step == 1:
                prompt = text
                
                # Conversational Filler (Latency Hiding)
                async def generate_filler():
                    try:
                        filler_prompt = f"System: Write a short, empathetic, 3-5 word acknowledgment for the user's request. Do not answer it, just acknowledge. E.g. 'Working on it', 'I'll look into it', 'Sure thing!'.\nUser: {text}\nAcknowledgment: "
                        local_client = self.reasoning.router.local_client
                        if local_client:
                            filler = await local_client.generate(filler_prompt, max_tokens=15)
                            if filler:
                                filler = filler.strip('"\'').strip()
                                event_bus.emit("pipeline.filler_ready", {"text": filler})
                    except Exception:
                        pass
                asyncio.create_task(generate_filler())
                
            else:
                trace_str = json.dumps(trace, ensure_ascii=False, default=str, indent=2)
                prompt = (
                    f"{text}\n\n"
                    f"[MULTI-STEP CONTEXT — Step {step}/{self.max_steps}]\n"
                    f"Previous actions and results:\n{trace_str}\n\n"
                    f"Continue working towards the user's goal. "
                    f"If the task is COMPLETE, respond with ONLY your final answer (no tool calls). "
                    f"If more actions are needed, emit tool calls."
                )

            thought = await self.reasoning.think(prompt, sensor_data=sensor_data, tools=tools)
            calls = thought.get("calls", []) or []
            text_response = thought.get("text", "") or ""

            # If no tool calls, the LLM considers the task done
            if not calls:
                final_ok = True
                break

            # Execute calls (with approval check in secure mode)
            results, ok = await self._execute_calls(calls)
            all_calls.extend(calls)
            all_results.extend(results)

            # ── Post-Action Verification ─────────────────────────────────────
            # For each call+result pair, attempt empirical verification.
            # This prevents WIS from claiming success without real evidence.
            for call, result in zip(calls, results):
                verified = result.get("ok", result.get("success", False))
                verification_note = ""

                try:
                    skill = call.get("skill", "") or ""
                    action = call.get("action", "") or ""
                    output = result.get("output") or result.get("data") or {}

                    # Verify process launch
                    if action in ("open_application", "launch", "execute") or "open" in action:
                        pid = output.get("pid") if isinstance(output, dict) else None
                        if pid:
                            import psutil
                            if psutil.pid_exists(int(pid)):
                                verified = True
                                verification_note = f"PID {pid} confirmed running."
                            else:
                                verified = False
                                verification_note = f"PID {pid} NOT found — process may have crashed."
                        else:
                            verification_note = "No PID returned — cannot confirm process started."

                    # Verify file creation/write
                    elif action in ("write_file", "save_file", "create_file", "write") or "file" in action:
                        import os
                        path = (
                            output.get("path") or output.get("file_path") or output.get("wav_path")
                            if isinstance(output, dict) else None
                        )
                        if path and os.path.exists(path):
                            size = os.path.getsize(path)
                            verified = True
                            verification_note = f"File confirmed on disk: {path} ({size} bytes)."
                        elif path:
                            verified = False
                            verification_note = f"File NOT found on disk: {path}"
                        else:
                            verification_note = "No file path returned — cannot confirm file exists."

                except Exception as vex:
                    verification_note = f"Verification skipped: {vex}"

                # Record in structured trace
                trace.append({
                    "step": step,
                    "call": call,
                    "result": result,
                    "verified": verified,
                    "verification_note": verification_note,
                })
                if not verified:
                    ok = False

            # Build trace summary for LLM context (structured JSON, not free text)
            trace_json = json.dumps(trace, ensure_ascii=False, default=str, indent=2)

            if not ok:
                # Auto-repair attempt
                failed_msgs = [
                    r.get("reason") or (r.get("output", {}) or {}).get("message")
                    or (r.get("output", {}) or {}).get("error")
                    for r in results if not r.get("ok", False)
                ]
                error_desc = " | ".join(str(m) for m in failed_msgs if m)
                category = FailureClassifier.classify(error_desc)
                event_bus.emit("pipeline.failure_classified", {
                    "category": category, "error": error_desc, "text": text[:80]
                })

                repair_prompt = (
                    f"{text}\n\n"
                    f"[AUTO-REPAIR — Step {step}]: Previous action failed ({category}): {error_desc}.\n"
                    f"Please consult the ## AVAILABLE TOOLS AND SCHEMAS section in the system prompt to find the correct, canonical tool and action name, along with their exact parameter schemas.\n"
                    f"Generate alternative tool calls or parameters."
                )
                try:
                    repair_thought = await self.reasoning.think(repair_prompt, sensor_data=sensor_data, tools=tools)
                    repair_calls = repair_thought.get("calls", []) or []
                    if repair_calls:
                        repair_results, repair_ok = await self._execute_calls(repair_calls)
                        if repair_ok:
                            text_response = repair_thought.get("text", "") or text_response
                            all_calls.extend(repair_calls)
                            all_results.extend(repair_results)
                            ok = True
                            for rc, rr in zip(repair_calls, repair_results):
                                trace.append({
                                    "step": step,
                                    "call": rc,
                                    "result": rr,
                                    "verified": rr.get("ok", False),
                                    "verification_note": "auto-repair",
                                })
                except Exception as exc:
                    logger.warning(f"pipeline: auto-repair failed: {exc}")

            final_ok = ok

            # Post-exec synthesis + MetaCognitive Verification
            if step == self.max_steps or not calls:
                try:
                    verified_count = sum(1 for t in trace if t.get("verified"))
                    failed_count = len(trace) - verified_count
                    synth_prompt = (
                        f"{text}\n\n"
                        f"[POST-EXECUTION SYNTHESIS]\n"
                        f"Execution trace (structured — {verified_count} verified, {failed_count} failed/unconfirmed):\n"
                        f"{json.dumps(trace, ensure_ascii=False, default=str, indent=2)}\n\n"
                        f"IMPORTANT INSTRUCTIONS FOR YOUR RESPONSE:\n"
                        f"- Report ONLY outcomes confirmed in the trace above (verified=true).\n"
                        f"- For any action where verified=false, acknowledge it honestly.\n"
                        f"- Do NOT invent results, file paths, or states not present in the trace.\n"
                        f"- Be concise and factual. Avoid inventing checkmarks for unverified steps."
                    )
                    synth = await self.reasoning.think(synth_prompt, sensor_data=sensor_data)
                    if synth.get("text"):
                        text_response = synth["text"].strip()
                except Exception as exc:
                    logger.warning(f"pipeline: synthesis skipped: {exc}")

                # ── MetaCognitive Verification ─────────────────────────────
                verification = _verifier.verify(
                    agent_response=text_response,
                    tool_results=all_results,
                    action_trace=trace,
                )
                if not verification.passed:
                    event_bus.emit("pipeline.metacognitive_correction", {
                        "issue": verification.issue,
                        "severity": verification.severity,
                    })
                    if verification.reflection_prompt and verification.severity == "critical":
                        try:
                            reflection = await self.reasoning.think(
                                verification.reflection_prompt, sensor_data=sensor_data
                            )
                            if reflection.get("text"):
                                text_response = reflection["text"].strip()
                        except Exception as exc:
                            logger.warning(f"pipeline: reflection skipped: {exc}")

        event_bus.emit("pipeline.loop_done", {
            "steps": step_count, "max_steps": self.max_steps,
            "success": final_ok, "text": text[:80],
        })

        # ── Guard: si ambos LLMs (API + local) fallaron, no devolver silencio ──
        if not (text_response or "").strip():
            text_response = (
                "I'm sorry, I couldn't reach my language model right now "
                "(offline or connection error). Please check the API key / network "
                "and try again."
            )
            final_ok = False
            event_bus.emit("pipeline.empty_response_fallback", {"text": text[:80]})

        try:
            self.reasoning.memory.remember(text, text_response)
            
            # Trigger background memory compression
            local_client = self.reasoning.router.local_client
            if local_client:
                asyncio.create_task(self.reasoning.memory.compress_history(local_client))
        except Exception:
            logger.warning("pipeline: could not remember interaction.")

        if final_ok:
            self.skill_memory.record_success(text, all_calls, text_response)
        else:
            self.skill_memory.record_failure(text, all_calls)

        return {
            "response": text_response,
            "calls": all_calls,
            "results": all_results,
            "success": final_ok,
            "steps_used": step_count,
            "raw_response": "",
            "model_used": "",
        }

    # ---- Execute Calls (with approval) ------------------------------------

    # ── Autonomous telemetry trigger handler ────────────────────────────────

    async def handle_autonomous_trigger(self, event: Dict[str, Any]) -> None:
        """Called by TelemetryEngine when a threshold rule fires.
        Processes the action autonomously without waiting for user input.
        """
        prompt = event.get("action_prompt", "")
        sensor_data = event.get("readings")
        if not prompt:
            return
        logger.info("pipeline: autonomous trigger fired: %s", prompt[:80])
        event_bus.emit("pipeline.autonomous_trigger", {"prompt": prompt[:80]})
        try:
            await self.process(prompt, sensor_data=sensor_data)
        except Exception as exc:
            logger.error("pipeline: autonomous trigger failed: %s", exc)

    async def _execute_calls(self, calls: List[Dict[str, Any]]) -> tuple:
        if not calls:
            return [], True

        results: List[Dict[str, Any]] = []
        all_ok = True

        # Partition calls: risky ones need approval (sequential),
        # safe ones run in parallel via asyncio.gather for speed.
        safe_calls = [c for c in calls if not self.safety.needs_approval(c)]
        risky_calls = [c for c in calls if self.safety.needs_approval(c)]

        # Execute safe calls in parallel
        if safe_calls:
            safe_results = await asyncio.gather(
                *[self._execute_single_call(c) for c in safe_calls],
                return_exceptions=False,
            )
            results.extend(safe_results)
            if any(not r.get("ok", False) for r in safe_results):
                all_ok = False

        # Execute risky calls sequentially (approval required)
        for call in risky_calls:
            r = await self._execute_single_call(call, require_approval=True)
            results.append(r)
            if not r.get("ok", False):
                all_ok = False

        return results, all_ok

    async def _execute_single_call(
        self, call: Dict[str, Any], require_approval: bool = False
    ) -> Dict[str, Any]:
        """Execute a single tool call with safety, optional approval gate, and dispatch."""
        if not isinstance(call, dict):
            return {"error": "invalid_call", "call": call, "ok": False}

        # Hard safety block
        allowed, reason = self.safety.check(call)
        if not allowed:
            call_name = call.get("skill") or call.get("name") or "unknown"
            event_bus.emit("pipeline.call_blocked", {"name": call_name, "reason": reason})
            return {"blocked": True, "reason": reason, "name": call_name, "ok": False}

        # Approval gate
        if require_approval:
            call_name = (
                call.get("skill") or call.get("name") or
                call.get("action") or call.get("tool") or "unknown"
            )
            event_bus.emit("pipeline.approval_required", {
                "call": call, "name": call_name,
                "action": call.get("action") or call.get("tool") or "",
                "params": call.get("params") or call.get("arguments") or {},
            })
            self._approval_event = asyncio.Event()
            self._approval_result = False
            try:
                await asyncio.wait_for(self._approval_event.wait(), timeout=120)
            except asyncio.TimeoutError:
                self._approval_result = False
            if not self._approval_result:
                event_bus.emit("pipeline.call_denied", {"name": call_name})
                return {
                    "ok": False, "name": call_name,
                    "action": call.get("action") or "",
                    "output": {"error": "denied_by_user"},
                }
            event_bus.emit("pipeline.call_approved", {"name": call_name})

        # Resolve skill / action / params
        skill_name = str(call.get("skill") or call.get("name") or call.get("tool") or "").strip()
        raw_action = str(call.get("action") or "").strip()
        raw_type = str(call.get("type") or "").strip()

        if isinstance(call.get("params"), dict):
            params = dict(call["params"])
        elif isinstance(call.get("arguments"), dict):
            params = dict(call["arguments"])
        else:
            params = {
                k: v for k, v in call.items()
                if k not in ("skill", "name", "action", "type", "domain", "tool", "params", "arguments")
            }

        if "command" in call and "command" not in params:
            params["command"] = call["command"]
        if "app_name" in call and "app_name" not in params:
            params["app_name"] = call["app_name"]

        action = raw_action or skill_name
        if not action or action in ("exec", "shell", "cmd", "powershell", "bash", "run"):
            if raw_type in ("exec", "shell", "cmd", "powershell", "bash", "run") or "command" in params:
                action = "execute_shell"
            elif "app_name" in params or "application" in params:
                action = "open_application"
            elif "query" in params:
                action = "web_search"
            elif "level" in params or "volume" in params:
                action = "set_volume"

        if not skill_name and self.abilities:
            if hasattr(self.abilities, "all"):
                for ab_name, ab in self.abilities.all().items():
                    supported = [a.get("action", "").lower() for a in ab.get_schema() if isinstance(a, dict)]
                    if (
                        action.lower() in supported
                        or action.lower() == ab_name.lower()
                        or action.lower() == ab.domain.lower()
                    ):
                        skill_name = ab_name
                        break

        event_bus.emit("pipeline.call_start", {"skill": skill_name, "action": action, "params": params})

        output = None
        success = False

        if hasattr(self.abilities, "execute") and callable(getattr(self.abilities, "execute")):
            try:
                res = await self.abilities.execute(skill_name, action, params)
                output = res
                success = res.get("success", False) if isinstance(res, dict) else True
            except Exception as exc:
                logger.warning("pipeline: ability execute failed: %s", exc)
                output = {"error": str(exc)}
                success = False
        elif isinstance(self.abilities, dict):
            fn = self.abilities.get(skill_name) or self.abilities.get(action)
            if fn is None:
                output = {"error": "unknown_ability", "name": skill_name or action}
                success = False
            else:
                try:
                    if inspect.iscoroutinefunction(fn):
                        output = await fn(call)
                    else:
                        output = fn(call)
                    success = True
                except Exception as exc:
                    output = {"error": str(exc)}
                    success = False
        else:
            output = {"error": "no_abilities_registered"}
            success = False

        event_bus.emit("pipeline.call_result", {
            "skill": skill_name, "action": action,
            "success": success, "output": output,
        })
        return {"ok": success, "name": skill_name or action, "action": action, "output": output}

    @staticmethod
    def _finalize(result: Dict[str, Any], path: str, success: bool) -> Dict[str, Any]:
        final_dict = {
            "response": result.get("response", ""),
            "calls": result.get("calls", []),
            "results": result.get("results", []),
            "path_used": path,
            "success": bool(result.get("success", success)),
            "steps_used": result.get("steps_used", 1),
        }
        event_bus.emit("pipeline.response_ready", final_dict)
        return final_dict
