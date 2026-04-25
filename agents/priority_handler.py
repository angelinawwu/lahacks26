"""
Priority Handler Agent.

Receives an AlertMessage from the Operator, classifies severity (P1-P4)
using ASI-1 Mini, applies guardrails, and returns a PriorityResponse.

Guardrails emitted as flags (downstream Case Handler / Operator enforce):
  - "enforce_page_load_limit"  : for P3/P4, skip clinicians with >3 pages/hr
  - "require_on_call"           : suppress off-shift unless explicitly on-call
  - "ambiguous_needs_review"    : input ambiguous; default P2, flag for human
  - "sparse_input"              : <10 words — emergency / minimal-input mode
"""
from __future__ import annotations
import os
import json

from dotenv import load_dotenv
from uagents import Agent, Context

from agents.models import AlertMessage, PriorityResponse
from agents.asi_client import asi1_chat, extract_json

load_dotenv()

SEED = os.getenv("PRIORITY_SEED", "priority-handler-dev-seed")
PORT = int(os.getenv("PRIORITY_PORT", "8002"))

agent = Agent(
    name="priority_handler",
    seed=SEED,
    port=PORT,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)

SYSTEM_PROMPT = """You are the Priority Handler in a hospital paging system.

Classify each clinical alert into EXACTLY ONE of:
  P1 — code / immediate life threat (cardiac arrest, stroke, major trauma, airway)
  P2 — urgent, needs clinician within minutes (chest pain, sepsis, significant bleeding)
  P3 — important, within the hour (pain control, non-critical consults)
  P4 — routine (lab follow-up, med reconciliation)

Rules:
  - If the alert is ambiguous, sparse, or you are unsure, choose P2 — NEVER ask
    for clarification. Minimal input in an ED context = assume worst plausible case.
  - Any mention of: arrest, code blue, stroke, STEMI, anaphylaxis, unresponsive,
    not breathing, massive bleed, airway → P1.
  - Flag ambiguous alerts so a human operator can review after dispatch.

Respond with ONLY a JSON object, no prose:
{"priority":"P1|P2|P3|P4","reasoning":"one sentence","ambiguous":true|false}
"""

P1_KEYWORDS = (
    "arrest", "code blue", "stroke", "stemi", "anaphylaxis", "unresponsive",
    "not breathing", "no pulse", "massive bleed", "airway", "seizing",
)


def _keyword_fallback(text: str) -> tuple[str, str]:
    """Deterministic fallback when ASI-1 is unavailable."""
    low = text.lower()
    if any(k in low for k in P1_KEYWORDS):
        return "P1", f"Keyword match to P1 triggers in: '{text[:60]}'"
    # Default for ambiguous / minimal input per emergency-mode requirement.
    return "P2", "Fallback: ASI-1 unavailable, defaulting to P2 (safe-worst-case)."


def classify(alert: AlertMessage) -> PriorityResponse:
    text = alert.raw_text or ""
    words = text.split()
    flags: list[str] = []
    if len(words) < 10:
        flags.append("sparse_input")

    user_prompt = json.dumps({
        "raw_text": text,
        "room": alert.room,
        "specialty_hint": alert.specialty_hint,
        "symptoms": alert.symptoms,
    })
    raw = asi1_chat(SYSTEM_PROMPT, user_prompt)
    parsed = extract_json(raw) if raw else None

    fallback_used = False
    if parsed and parsed.get("priority") in {"P1", "P2", "P3", "P4"}:
        priority = parsed["priority"]
        reasoning = parsed.get("reasoning", "").strip() or "ASI-1 classification."
        ambiguous = bool(parsed.get("ambiguous"))
    else:
        priority, reasoning = _keyword_fallback(text)
        ambiguous = len(words) < 4
        fallback_used = True

    # Guardrails
    if ambiguous:
        flags.append("ambiguous_needs_review")
        if priority in {"P3", "P4"}:
            # Emergency mode: never leave ambiguous alerts at P3/P4
            priority = "P2"
            reasoning += " [Guardrail: ambiguous → upgraded to P2.]"

    if priority in {"P3", "P4"}:
        flags.append("enforce_page_load_limit")
    flags.append("require_on_call")  # always prefer on-call; downstream decides strictness

    return PriorityResponse(
        priority=priority,
        guardrail_flags=flags,
        reasoning=reasoning,
        fallback_used=fallback_used,
    )


@agent.on_event("startup")
async def _startup(ctx: Context):
    ctx.logger.info(f"[priority_handler] address={agent.address}")


@agent.on_message(model=AlertMessage, replies=PriorityResponse)
async def handle_alert(ctx: Context, sender: str, msg: AlertMessage):
    ctx.logger.info(f"[priority_handler] alert from {sender[:12]}…: {msg.raw_text!r}")
    resp = classify(msg)
    ctx.logger.info(
        f"[priority_handler] reasoning: priority={resp.priority} "
        f"flags={resp.guardrail_flags} fallback={resp.fallback_used} :: {resp.reasoning}"
    )
    await ctx.send(sender, resp)


if __name__ == "__main__":
    agent.run()
