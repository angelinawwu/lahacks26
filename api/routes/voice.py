"""
Voice-to-text urgent brief routes.
Replaces backend/routes/voice.py.

Imports voice_log from backend/ (added to sys.path by shared_state).
"""
from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from api import shared_state as state
from api.sio import sio

router = APIRouter()
_log = logging.getLogger("medpage.voice")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Transcription helpers
# ---------------------------------------------------------------------------

def _transcribe_openai(audio_bytes: bytes, mime: str) -> str:
    try:
        import openai  # type: ignore
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        import io as _io
        ext = "wav" if "wav" in mime else ("webm" if "webm" in mime else "m4a")
        audio_file = _io.BytesIO(audio_bytes)
        audio_file.name = f"recording.{ext}"
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
        )
        return transcript.text.strip()
    except Exception as exc:
        _log.warning("Whisper failed (%s); using stub", exc)
        return ""


def transcribe_audio(audio_bytes: bytes, mime: str = "audio/wav") -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        result = _transcribe_openai(audio_bytes, mime)
        if result:
            return result
    return "[voice transcription unavailable — set OPENAI_API_KEY]"


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

_PRIORITY_KEYWORDS = {
    "P1": ["code", "arrest", "crash", "critical", "stat", "immediate", "unresponsive",
           "seizing", "seizure", "hemorrhage", "cardiac arrest", "trauma"],
    "P2": ["urgent", "chest pain", "shortness of breath", "altered", "deteriorating",
           "bp drop", "hypotension", "tachycardia", "stroke", "sepsis"],
    "P3": ["pain", "fever", "nausea", "vomiting", "scheduled", "routine follow"],
}

_SPECIALTY_HINTS = {
    "cardiology": ["chest pain", "cardiac", "heart", "mi", "ekg", "ecg", "arrhythmia", "afib"],
    "neurology": ["stroke", "seizure", "neuro", "altered mental status", "aphasia", "hemiplegia"],
    "emergency_medicine": ["trauma", "accident", "fall", "overdose", "allergic", "anaphylaxis"],
    "pulmonology": ["breath", "respiratory", "oxygen", "saturation", "spo2", "copd", "asthma"],
    "surgery": ["surgical", "post-op", "appendicitis", "bowel", "perforation", "abscess"],
    "orthopedics": ["fracture", "orthopedic", "hip", "knee", "broken", "bone"],
    "gastroenterology": ["gi", "bleeding", "melena", "bowel", "gastric"],
    "nephrology": ["kidney", "renal", "creatinine", "dialysis", "aki"],
}

_ROOM_PATTERNS = re.compile(
    r"\b(icu|er|ed|or\s*\d*|nicu|picu|floor\s*\d+|room\s*\w+|bay\s*\w+"
    r"|ward\s*\w+|labor\s*(?:and\s*)?delivery|cath\s*lab)\b",
    re.IGNORECASE,
)

_PATIENT_PATTERNS = re.compile(
    r"\bpatient\s+(?:id\s*[:#]?\s*)?([a-z0-9_-]+)\b"
    r"|\bpt\s+([a-z0-9_-]+)\b",
    re.IGNORECASE,
)


def _parse_transcript(text: str) -> Dict[str, Any]:
    lower = text.lower()
    priority = "P3"
    for p, kws in _PRIORITY_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            priority = p
            break
    specialty_hint: Optional[str] = None
    for spec, kws in _SPECIALTY_HINTS.items():
        if any(kw in lower for kw in kws):
            specialty_hint = spec
            break
    room_match = _ROOM_PATTERNS.search(text)
    room = room_match.group(0).strip().lower().replace(" ", "_") if room_match else None
    patient_id: Optional[str] = None
    pm = _PATIENT_PATTERNS.search(text)
    if pm:
        patient_id = (pm.group(1) or pm.group(2) or "").strip()
    return {
        "raw_text": text,
        "priority_hint": priority,
        "specialty_hint": specialty_hint,
        "room": room,
        "patient_id": patient_id,
    }


def _select_doctor(specialty_hint: Optional[str], zone: Optional[str]) -> Optional[str]:
    candidates = [d for d in state.DOCTORS.values() if d.get("status") in ("available", "on_break")]
    if not candidates:
        return None

    def _score(doc: dict) -> int:
        score = 0
        if specialty_hint and specialty_hint in (doc.get("specialty") or []):
            score += 10
        if doc.get("on_call"):
            score += 5
        if zone and doc.get("zone", "").startswith(zone.split("_")[0]):
            score += 3
        score -= doc.get("page_count_1hr", 0)
        return score

    return max(candidates, key=_score).get("id")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/api/voice/transcribe")
async def transcribe(request: Request):
    body = await request.json()
    transcript: str = body.get("transcript", "").strip()

    if not transcript:
        audio_b64 = body.get("audio_b64", "")
        if not audio_b64:
            raise HTTPException(status_code=400, detail="provide 'audio_b64' or 'transcript'")
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="audio_b64 is not valid base64")
        transcript = transcribe_audio(audio_bytes, body.get("mime_type", "audio/wav"))

    if not transcript:
        raise HTTPException(status_code=422, detail="transcription produced empty result")

    parsed = _parse_transcript(transcript)
    parsed["parsed_at"] = _now()
    requested_by = body.get("requested_by")
    parsed["requested_by"] = requested_by

    try:
        import voice_log  # type: ignore[import]
        event = voice_log.log_event(
            transcript=transcript,
            parsed=parsed,
            source="audio" if not body.get("transcript") else "transcript",
            requested_by=requested_by,
            endpoint="/api/voice/transcribe",
        )
        parsed["voice_event_id"] = event["id"]
        parsed["summary"] = event["summary"]
    except Exception:
        pass

    return parsed


@router.post("/api/voice/urgent", status_code=201)
async def voice_urgent(request: Request):
    """Transcribe + classify + dispatch a page immediately."""
    body = await request.json()
    transcript: str = body.get("transcript", "").strip()

    if not transcript:
        audio_b64 = body.get("audio_b64", "")
        if not audio_b64:
            raise HTTPException(status_code=400, detail="provide 'audio_b64' or 'transcript'")
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="audio_b64 is not valid base64")
        transcript = transcribe_audio(audio_bytes, body.get("mime_type", "audio/wav"))

    if not transcript:
        raise HTTPException(status_code=422, detail="transcription produced empty result")

    parsed = _parse_transcript(transcript)
    requested_by = body.get("requested_by")
    room = body.get("room") or parsed.get("room")
    patient_id = parsed.get("patient_id")
    priority = parsed.get("priority_hint", "P2")
    specialty_hint = parsed.get("specialty_hint")

    doctor_id: Optional[str] = _select_doctor(specialty_hint, room)
    if not doctor_id:
        for doc in state.DOCTORS.values():
            if doc.get("status") == "available":
                doctor_id = doc["id"]
                break

    if not doctor_id:
        raise HTTPException(
            status_code=503,
            detail={"error": "no available clinician found", "transcript": transcript, "parsed": parsed},
        )

    page_id = uuid4().hex
    created_at = _now()

    voice_event_id = None
    voice_summary = None
    try:
        import voice_log  # type: ignore[import]
        ve = voice_log.log_event(
            transcript=transcript,
            parsed={**parsed, "room": room, "patient_id": patient_id, "priority_hint": priority},
            source="audio" if not body.get("transcript") else "transcript",
            requested_by=requested_by,
            endpoint="/api/voice/urgent",
            linked_page_id=page_id,
        )
        voice_event_id = ve["id"]
        voice_summary = ve["summary"]
    except Exception:
        pass

    page = {
        "id": page_id,
        "source": "voice",
        "transcript": transcript,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "message": f"[VOICE] {transcript}",
        "priority": priority,
        "room": room,
        "requested_by": requested_by,
        "backup_doctors": [],
        "status": "paging",
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
        "escalation_history": [],
        "parsed_fields": parsed,
        "voice_event_id": voice_event_id,
        "voice_summary": voice_summary,
    }
    state.save_page(page)

    doc = state.DOCTORS.get(doctor_id, {})
    doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
    if patient_id:
        doc["active_cases"] = doc.get("active_cases", 0) + 1

    await sio.emit("doctor_paged", page, room="operators")
    await sio.emit(
        "incoming_page",
        {
            "page_id": page_id,
            "message": f"[VOICE URGENT] {transcript}",
            "patient_id": patient_id,
            "room": room,
            "priority": priority,
            "created_at": created_at,
            "ack_deadline_seconds": 45,
            "source": "voice",
        },
        room=doctor_id,
    )

    return page


@router.get("/api/voice/log")
async def voice_log_list(
    limit: int = 50,
    channel: Optional[str] = None,
    room: Optional[str] = None,
    since_minutes: Optional[int] = None,
):
    limit = max(1, min(limit, 500))
    try:
        import voice_log  # type: ignore[import]
        events = voice_log.recent_events(
            limit=limit,
            channel=channel,
            room=room,
            since_minutes=since_minutes,
        )
        return {"events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voice/log/recent")
async def voice_log_recent(minutes: int = 10):
    try:
        import voice_log  # type: ignore[import]
        events = voice_log.recent_events(limit=200, since_minutes=minutes)
        return {"events": events, "count": len(events), "window_minutes": minutes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voice/channels")
async def voice_log_channels():
    try:
        import voice_log  # type: ignore[import]
        return {"channels": voice_log.list_channels()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/voice/log/{event_id}")
async def voice_log_get(event_id: str):
    try:
        import voice_log  # type: ignore[import]
        event = voice_log.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="not found")
        return event
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
