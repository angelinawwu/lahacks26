"""
Brief Skill — SBAR clinician handoff generator.

Called by the Operator Agent the moment a clinician accepts a page. Produces
a sub-100-word SBAR brief (Situation, Background, Assessment, Request) using
ASI-1 Mini, with a deterministic fallback if the model is unavailable.

Designed to be read while walking — short, scannable, no fluff.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agents.asi_client import asi1_chat
from agents.models import SBARBrief


SBAR_SYSTEM_PROMPT = """You are an ER charge nurse handing off a patient to an
incoming clinician via pager. Produce a SBAR brief.

HARD RULES:
- TOTAL output MUST be UNDER 100 words.
- Use exactly four labeled sections: S:, B:, A:, R:
- Each section is 1-2 short sentences. No filler. No greetings. No sign-off.
- Use clinical shorthand (HR, BP, SpO2, hx, c/o, s/p, etc) where natural.
- If a field is missing, write "unknown" — never invent vitals or labs.
- The clinician is walking while reading this. Optimize for scan-ability.

OUTPUT FORMAT (exactly):
S: <situation — why paged, room, acuity>
B: <background — relevant hx, meds, allergies, recent events>
A: <assessment — current vitals/findings, your read>
R: <request — specific ask, ETA expected>
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _word_count(text: str) -> int:
    return len(text.split())


def _truncate_to_word_limit(text: str, max_words: int = 100) -> str:
    """Truncate at word boundary if model overshoots."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _build_user_prompt(
    alert: Dict[str, Any],
    patient: Optional[Dict[str, Any]],
    scene: Optional[Dict[str, Any]],
) -> str:
    """Pack everything we know into a compact JSON-ish prompt for ASI-1."""
    lines = []

    # Alert
    lines.append("ALERT:")
    lines.append(f"  raw_text: {alert.get('raw_text', '')}")
    if alert.get("priority"):
        lines.append(f"  priority: {alert['priority']}")
    if alert.get("room"):
        lines.append(f"  room: {alert['room']}")
    if alert.get("specialty_hint"):
        lines.append(f"  specialty: {alert['specialty_hint']}")
    if alert.get("symptoms"):
        lines.append(f"  symptoms: {alert['symptoms']}")

    # Patient / EHR
    if patient:
        lines.append("PATIENT:")
        for key in (
            "name", "age", "sex", "primary_diagnosis", "comorbidities",
            "assigned_team", "primary_physician", "allergies", "medications",
        ):
            val = patient.get(key)
            if val:
                lines.append(f"  {key}: {val}")
        # vitals if present
        vitals = patient.get("vitals") or patient.get("latest_vitals")
        if vitals:
            lines.append(f"  vitals: {vitals}")
        # recent labs
        labs = patient.get("labs") or patient.get("recent_labs")
        if labs:
            lines.append(f"  recent_labs: {labs}")
        notes = patient.get("clinical_notes") or patient.get("notes")
        if notes:
            # Trim notes — they're often verbose
            note_text = str(notes)[:300]
            lines.append(f"  recent_notes: {note_text}")

    # Scene context (who paged, when, escalation history)
    if scene:
        lines.append("SCENE:")
        for key in ("requested_by", "paged_at", "escalated_from", "wait_time_seconds"):
            val = scene.get(key)
            if val is not None:
                lines.append(f"  {key}: {val}")

    return "\n".join(lines)


def _fallback_brief(
    alert: Dict[str, Any],
    patient: Optional[Dict[str, Any]],
) -> str:
    """Deterministic fallback when ASI-1 is unavailable. Stays <100 words."""
    room = alert.get("room") or "unknown"
    priority = alert.get("priority") or "P2"
    raw = (alert.get("raw_text") or "").strip()[:120]

    name = (patient or {}).get("name", "patient")
    dx = (patient or {}).get("primary_diagnosis", "unknown dx")
    comorbid = (patient or {}).get("comorbidities") or []
    comorbid_str = ", ".join(comorbid[:3]) if comorbid else "none documented"
    allergies = (patient or {}).get("allergies") or []
    allergy_str = ", ".join(allergies[:2]) if allergies else "NKDA"

    s = f"S: Room {room} {priority} — {raw or 'see alert'}."
    b = f"B: {name}, hx {dx}; comorbid: {comorbid_str}; allergies: {allergy_str}."
    a = "A: See alert. Vitals unknown — assess on arrival."
    r = "R: Bedside eval ASAP, confirm plan with ops on arrival."

    brief = f"{s}\n{b}\n{a}\n{r}"
    return _truncate_to_word_limit(brief, 100)


async def generate_brief(
    alert: Dict[str, Any],
    patient: Optional[Dict[str, Any]] = None,
    scene: Optional[Dict[str, Any]] = None,
    *,
    page_id: str = "",
    clinician_id: str = "",
) -> SBARBrief:
    """
    Generate a sub-100-word SBAR brief for a clinician who just accepted a page.

    Args:
        alert:    dict with at minimum {"raw_text": str}; may include
                  room, priority, specialty_hint, symptoms.
        patient:  optional EHR/patient dict (name, dx, meds, vitals, ...).
        scene:    optional context (requested_by, escalation history, ...).
        page_id:  page id this brief is associated with (for tracking).
        clinician_id: receiving clinician id.

    Returns:
        SBARBrief — guaranteed <=100 words; never raises.
    """
    user_prompt = _build_user_prompt(alert, patient, scene)

    # Run ASI-1 in a thread so we don't block the event loop
    raw = await asyncio.to_thread(
        asi1_chat,
        SBAR_SYSTEM_PROMPT,
        user_prompt,
        0.2,
        8.0,  # tight timeout — clinician is waiting
    )

    if raw and raw.strip():
        text = raw.strip()
        # Strip code fences if model added them
        if text.startswith("```"):
            text = text.strip("`").lstrip("\n")
            if text.lower().startswith(("text\n", "sbar\n")):
                text = text.split("\n", 1)[1] if "\n" in text else text
        # Sanity check the format — must contain S: B: A: R:
        if not all(tag in text for tag in ("S:", "B:", "A:", "R:")):
            text = _fallback_brief(alert, patient)
        else:
            text = _truncate_to_word_limit(text, 100)
    else:
        text = _fallback_brief(alert, patient)

    return SBARBrief(
        page_id=page_id,
        clinician_id=clinician_id,
        patient_id=(patient or {}).get("patient_id") or (patient or {}).get("id"),
        brief_text=text,
        word_count=_word_count(text),
        generated_at=_now_iso(),
    )


# Convenience sync wrapper for callers that aren't in an async context
def generate_brief_sync(
    alert: Dict[str, Any],
    patient: Optional[Dict[str, Any]] = None,
    scene: Optional[Dict[str, Any]] = None,
    *,
    page_id: str = "",
    clinician_id: str = "",
) -> SBARBrief:
    return asyncio.run(
        generate_brief(
            alert, patient, scene,
            page_id=page_id, clinician_id=clinician_id,
        )
    )
