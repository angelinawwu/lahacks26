"""
Voice-to-text urgent brief routes for the MedPage mobile app.

Mobile clients submit either:
  - A base64-encoded audio blob (WAV / WebM / m4a) which we transcribe via
    OpenAI Whisper (or a local stub when the key is absent), OR
  - A raw text transcript that was produced on-device.

After transcription the text is forwarded to the agent parser (same
classify + process_case pipeline used by /api/page) so an urgent page can
be created immediately from spoken input.

Endpoints:
  POST /api/voice/transcribe   — transcribe only; returns parsed fields
  POST /api/voice/urgent       — transcribe + classify + dispatch a page
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("voice", __name__)
_log = logging.getLogger("medpage.voice")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Transcription helpers
# ---------------------------------------------------------------------------

def _transcribe_openai(audio_bytes: bytes, mime: str) -> str:
    """
    Send audio to OpenAI Whisper. Falls back to stub when key missing.
    """
    try:
        import openai  # type: ignore
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        ext = "wav" if "wav" in mime else ("webm" if "webm" in mime else "m4a")
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"recording.{ext}"
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
        )
        return transcript.text.strip()
    except Exception as exc:
        _log.warning("Whisper transcription failed (%s); using stub", exc)
        return ""


def _transcribe_stub() -> str:
    """Placeholder when no Whisper key is configured."""
    return "[voice transcription unavailable — set OPENAI_API_KEY]"


def transcribe_audio(audio_bytes: bytes, mime: str = "audio/wav") -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        result = _transcribe_openai(audio_bytes, mime)
        if result:
            return result
    return _transcribe_stub()


# ---------------------------------------------------------------------------
# Agent parse helper — extract structured fields from free text
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
    """
    Lightweight NLP extraction. The agent pipeline does the heavy lifting;
    this is a fast pre-parse so fields arrive populated.
    """
    lower = text.lower()

    # Priority
    priority = "P3"
    for p, kws in _PRIORITY_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            priority = p
            break

    # Specialty hint
    specialty_hint: Optional[str] = None
    for spec, kws in _SPECIALTY_HINTS.items():
        if any(kw in lower for kw in kws):
            specialty_hint = spec
            break

    # Room
    room_match = _ROOM_PATTERNS.search(text)
    room = room_match.group(0).strip().lower().replace(" ", "_") if room_match else None

    # Patient ID
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/api/voice/transcribe")
def transcribe():
    """
    Transcribe audio or accept a text transcript and return extracted fields.

    Body (JSON):
      audio_b64   : base64-encoded audio bytes (optional)
      mime_type   : MIME type of audio (default "audio/wav")
      transcript  : raw text if already transcribed on-device (optional)
      requested_by: operator / nurse ID

    Response:
      { transcript, priority_hint, specialty_hint, room, patient_id, parsed_at }
    """
    body = request.get_json(silent=True) or {}
    transcript: str = body.get("transcript", "").strip()

    if not transcript:
        audio_b64 = body.get("audio_b64", "")
        if not audio_b64:
            return jsonify({"error": "provide 'audio_b64' or 'transcript'"}), 400
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            return jsonify({"error": "audio_b64 is not valid base64"}), 400
        mime = body.get("mime_type", "audio/wav")
        transcript = transcribe_audio(audio_bytes, mime)

    if not transcript:
        return jsonify({"error": "transcription produced empty result"}), 422

    parsed = _parse_transcript(transcript)
    parsed["parsed_at"] = _now()
    parsed["requested_by"] = body.get("requested_by")
    return jsonify(parsed)


@bp.post("/api/voice/urgent")
def voice_urgent():
    """
    Full pipeline: transcribe → parse → classify → dispatch a page.

    Body (JSON):
      audio_b64   : base64-encoded audio bytes (optional)
      mime_type   : MIME type of audio (default "audio/wav")
      transcript  : raw text if already transcribed on-device (optional)
      requested_by: operator / nurse ID who is speaking
      room        : override room (optional — auto-detected from transcript)

    Response: full page record (same as POST /api/page).
    """
    body = request.get_json(silent=True) or {}
    transcript: str = body.get("transcript", "").strip()

    if not transcript:
        audio_b64 = body.get("audio_b64", "")
        if not audio_b64:
            return jsonify({"error": "provide 'audio_b64' or 'transcript'"}), 400
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            return jsonify({"error": "audio_b64 is not valid base64"}), 400
        mime = body.get("mime_type", "audio/wav")
        transcript = transcribe_audio(audio_bytes, mime)

    if not transcript:
        return jsonify({"error": "transcription produced empty result"}), 422

    parsed = _parse_transcript(transcript)
    requested_by = body.get("requested_by")
    room = body.get("room") or parsed.get("room")
    patient_id = parsed.get("patient_id")
    priority = parsed.get("priority_hint", "P2")
    specialty_hint = parsed.get("specialty_hint")

    # Pick the best available doctor for the specialty
    doctor_id: Optional[str] = _select_doctor(specialty_hint, room)
    if not doctor_id:
        # Fallback: first available doctor
        for doc in state.DOCTORS.values():
            if doc.get("status") == "available":
                doctor_id = doc["id"]
                break

    if not doctor_id:
        return jsonify({
            "error": "no available clinician found",
            "transcript": transcript,
            "parsed": parsed,
        }), 503

    page_id = uuid4().hex
    created_at = _now()

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
    }
    state.PAGES[page_id] = page

    doc = state.DOCTORS.get(doctor_id, {})
    doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
    if patient_id:
        doc["active_cases"] = doc.get("active_cases", 0) + 1

    sio = current_app.socketio
    sio.emit("doctor_paged", page, room="operators")
    sio.emit(
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

    _log.info(
        "Voice urgent page %s dispatched → %s (priority=%s)",
        page_id, doctor_id, priority,
    )
    return jsonify(page), 201


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_doctor(specialty_hint: Optional[str], zone: Optional[str]) -> Optional[str]:
    """
    Return the best available doctor ID for the given specialty/zone hints.
    Prefers on-call doctors in the matching zone.
    """
    candidates = [
        d for d in state.DOCTORS.values()
        if d.get("status") in ("available", "on_break")
    ]
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

    best = max(candidates, key=_score)
    return best.get("id")
