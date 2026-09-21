"""WIS MetaCognitive Verifier — Self-Critique & Reflection Gate.
=================================================================
Ported and extended from AVRORA's core/pipeline/verifier.py.

Evaluates agent responses AFTER tool execution to detect:
1. Unhandled tool errors or contradictory success claims.
2. Missing deliverables (promised files, firmware, data that failed creation).
3. Hallucinated facts that conflict with actual tool observations.
4. Hardware-specific failures: Serial no-ACK, MQTT QoS miss, .hex not generated.

Zero latency impact on conversational turns — only activates when tools executed.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("wis.core.verifier")


# ─── Verification Result ────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """Result of a metacognitive verification check."""
    passed: bool
    issue: Optional[str] = None
    reflection_prompt: Optional[str] = None
    severity: str = "none"  # "none" | "warning" | "critical"


# ─── Main Verifier ──────────────────────────────────────────────────────────

class MetacognitiveVerifier:
    """Evaluates agent responses post-tool execution to ensure grounded, honest outcomes."""

    # Indicators that a tool result contains an error
    _ERROR_INDICATORS = (
        "failed", "failure", "error:", "[error]", "error ", "exception",
        "traceback", "not found", "permission denied", "syntaxerror",
        "timed out", "errno", "no such file", "connectionrefused",
        "timeout", "unreachable", "refused", "invalid", "aborted",
    )

    # English patterns that claim success
    _SUCCESS_CLAIM_EN = re.compile(
        r"(?:successfully\s+(?:created|executed|written|compiled|flashed|uploaded|installed|saved|generated|completed)|"
        r"(?:file|firmware|script|report)\s+(?:created|saved|written|generated)\s+(?:at|to|in)|"
        r"(?:task|mission|operation)\s+completed\s+successfully|"
        r"(?:connected|established|opened)\s+(?:successfully|to)|"
        r"(?:sent|published|transmitted)\s+successfully|"
        r"(?:flashed|uploaded)\s+successfully|"
        r"done[.\s]|completed[.\s])",
        re.IGNORECASE,
    )

    # Patterns for file deliverable promises
    _FILE_PROMISE = re.compile(
        r"(?:saved|written|created|generated)\s+(?:to|at|in)\s+[`'\"]?([^\s`'\"]+\.\w+)[`'\"]?",
        re.IGNORECASE,
    )

    # Patterns for hardware deliverable promises
    _FIRMWARE_PROMISE = re.compile(
        r"(?:compiled|built|generated)\s+(?:firmware|binary|hex|elf|bin)\s*(?:at|to|in)?\s*[`'\"]?([^\s`'\"]+\.(?:hex|bin|elf))[`'\"]?",
        re.IGNORECASE,
    )

    def verify(
        self,
        agent_response: str,
        tool_results: list[dict[str, Any]],
        action_trace: list[dict[str, Any]] | None = None,
    ) -> VerificationResult:
        """
        Primary verification entry point.

        Args:
            agent_response: The text response the agent wants to emit.
            tool_results: List of raw tool result dicts from _execute_calls().
            action_trace: Structured trace list from pipeline._try_new().

        Returns:
            VerificationResult with passed=True if OK, or issue + reflection prompt.
        """
        if not tool_results:
            return VerificationResult(passed=True)

        # 1. Check for error indicators in tool results vs claimed success
        result = self._check_error_vs_claim(agent_response, tool_results)
        if not result.passed:
            return result

        # 2. Check for promised file deliverables that don't exist on disk
        result = self._check_file_deliverables(agent_response, tool_results)
        if not result.passed:
            return result

        # 3. Check hardware-specific verifications
        result = self._check_hardware_verifications(action_trace or [])
        if not result.passed:
            return result

        # 4. Check for false verified flags in trace
        result = self._check_trace_integrity(agent_response, action_trace or [])
        if not result.passed:
            return result

        return VerificationResult(passed=True)

    # ── Internal Checks ──────────────────────────────────────────────────────

    def _check_error_vs_claim(
        self, response: str, tool_results: list[dict[str, Any]]
    ) -> VerificationResult:
        """Detects agent claiming success when tool results contain errors."""
        has_error = any(
            any(ind in str(r).lower() for ind in self._ERROR_INDICATORS)
            for r in tool_results
            if not r.get("ok", r.get("success", True))
        )
        if not has_error:
            return VerificationResult(passed=True)

        # Now check if agent is claiming success despite errors
        if self._SUCCESS_CLAIM_EN.search(response):
            # Collect actual error messages
            errors = []
            for r in tool_results:
                if not r.get("ok", r.get("success", True)):
                    out = r.get("output") or r.get("data") or {}
                    msg = (
                        out.get("message") or out.get("error")
                        if isinstance(out, dict) else str(out)
                    ) or r.get("reason", "unknown error")
                    errors.append(str(msg)[:200])

            error_summary = " | ".join(errors) or "tool returned failure"
            return VerificationResult(
                passed=False,
                issue=f"Agent claims success but tools reported errors: {error_summary}",
                severity="critical",
                reflection_prompt=(
                    f"[METACOGNITIVE CORRECTION] Your response claims success but tools "
                    f"reported the following errors: {error_summary}. "
                    f"You MUST revise your response to honestly report these failures. "
                    f"Do NOT claim success. Report exactly what failed and why."
                ),
            )

        return VerificationResult(passed=True)

    def _check_file_deliverables(
        self, response: str, tool_results: list[dict[str, Any]]
    ) -> VerificationResult:
        """Checks that files promised in the response actually exist on disk."""
        # Extract file paths from response
        promised_files = self._FILE_PROMISE.findall(response)
        promised_files += self._FIRMWARE_PROMISE.findall(response)

        missing = []
        for fp in promised_files:
            fp = fp.strip().strip("'\"` ")
            if fp and len(fp) > 3:
                # Try to find it in tool results first (authoritative)
                found_in_results = any(
                    fp in str(r.get("output", "")) or fp in str(r.get("data", ""))
                    for r in tool_results
                )
                if not found_in_results and not os.path.exists(fp):
                    # Check relative to common roots
                    base_path = str(Path(__file__).resolve().parent.parent)
                    for root in (base_path, ".", "Data"):
                        candidate = Path(root) / fp
                        if candidate.exists():
                            found_in_results = True
                            break
                if not found_in_results:
                    missing.append(fp)

        if missing:
            return VerificationResult(
                passed=False,
                issue=f"Promised files not found on disk: {missing}",
                severity="critical",
                reflection_prompt=(
                    f"[METACOGNITIVE CORRECTION] Your response references the following "
                    f"files that do not exist on disk: {missing}. "
                    f"NEVER claim a file was created unless you can verify it exists. "
                    f"Revise your response to accurately reflect what was actually produced."
                ),
            )

        return VerificationResult(passed=True)

    def _check_hardware_verifications(
        self, trace: list[dict[str, Any]]
    ) -> VerificationResult:
        """Hardware-specific post-execution checks: Serial ACK, MQTT QoS, firmware size."""
        for entry in trace:
            call = entry.get("call", {})
            result = entry.get("result", {})
            action = str(call.get("action", "")).lower()
            verified = entry.get("verified", True)
            output = result.get("output") or {}

            # Serial write: check ACK expected
            if action in ("serial_write", "write_serial", "uart_write"):
                if not verified:
                    port = call.get("params", {}).get("port", "unknown")
                    return VerificationResult(
                        passed=False,
                        issue=f"Serial write to {port} not acknowledged by device.",
                        severity="warning",
                        reflection_prompt=(
                            f"[HARDWARE WARNING] Serial write to {port} completed but "
                            f"no device acknowledgment was received. "
                            f"Report that data was sent but receipt is unconfirmed. "
                            f"Suggest verifying the device is powered and responsive."
                        ),
                    )

            # Firmware compile: check .hex/.bin exists and has content
            if action in ("compile", "build", "toolchain_compile", "pio_build"):
                out_file = (
                    output.get("output_file") or output.get("hex_path") or output.get("bin_path")
                    if isinstance(output, dict) else None
                )
                if out_file:
                    p = Path(out_file)
                    if not p.exists() or p.stat().st_size == 0:
                        return VerificationResult(
                            passed=False,
                            issue=f"Compile reported success but output file missing or empty: {out_file}",
                            severity="critical",
                            reflection_prompt=(
                                f"[HARDWARE CRITICAL] Compilation claimed success but the output "
                                f"firmware file '{out_file}' is missing or empty on disk. "
                                f"This means the build actually FAILED. "
                                f"Report compilation failure and include any stderr output."
                            ),
                        )

            # MQTT publish: check QoS confirmation
            if action in ("mqtt_publish", "publish", "mqtt_send"):
                if isinstance(output, dict) and output.get("qos", 0) > 0:
                    if not output.get("qos_confirmed", False):
                        topic = call.get("params", {}).get("topic", "unknown")
                        return VerificationResult(
                            passed=False,
                            issue=f"MQTT publish to {topic} with QoS>0 not confirmed by broker.",
                            severity="warning",
                            reflection_prompt=(
                                f"[HARDWARE WARNING] MQTT message published to '{topic}' with "
                                f"QoS > 0 but broker confirmation was not received. "
                                f"Report as potentially undelivered."
                            ),
                        )

        return VerificationResult(passed=True)

    def _check_trace_integrity(
        self, response: str, trace: list[dict[str, Any]]
    ) -> VerificationResult:
        """Checks that agent doesn't claim verified=True for steps that failed."""
        failed_but_not_acknowledged = []
        for entry in trace:
            if not entry.get("verified", True):
                call = entry.get("call", {})
                action = str(call.get("action", call.get("skill", "unknown")))
                # If response doesn't mention failure for this action, flag it
                if action not in response.lower() and "fail" not in response.lower():
                    failed_but_not_acknowledged.append(action)

        if failed_but_not_acknowledged:
            return VerificationResult(
                passed=False,
                issue=f"Unacknowledged failures in trace: {failed_but_not_acknowledged}",
                severity="warning",
                reflection_prompt=(
                    f"[METACOGNITIVE WARNING] The following actions failed or were unverified "
                    f"but are not mentioned in your response: {failed_but_not_acknowledged}. "
                    f"Be transparent about all failures, even partial ones."
                ),
            )

        return VerificationResult(passed=True)
