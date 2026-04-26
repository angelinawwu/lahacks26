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
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import Blueprint, jsonify, request, current_app
import state
import voice_log

bp = Blueprint("voice", __name__)
_log = logging.getLogger("medpage.voice")


def _room_size(sio, room: str, namespace: str = "/") -> int:
    try:
        ns_rooms = sio.server.manager.rooms.get(namespace, {})
        members = ns_rooms.get(room) or {}
        return len(members)
    except Exception:
        return -1


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
    requested_by = body.get("requested_by")
    parsed["requested_by"] = requested_by

    event = voice_log.log_event(
        transcript=transcript,
        parsed=parsed,
        source="audio" if not body.get("transcript") else "transcript",
        requested_by=requested_by,
        endpoint="/api/voice/transcribe",
    )
    parsed["voice_event_id"] = event["id"]
    parsed["summary"] = event["summary"]
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
    cid = (request.headers.get("X-Correlation-Id") or uuid4().hex[:8])[:32]

    _log.info(
        "voice.urgent start cid=%s priority=%s specialty=%s room=%s requested_by=%s",
        cid, priority, specialty_hint, room, requested_by,
    )

    # Pick the best available doctor for the specialty
    t0 = time.monotonic()
    doctor_id: Optional[str] = _select_doctor(specialty_hint, room)
    _log.info(
        "voice.select cid=%s doctor_id=%s ms=%.1f",
        cid, doctor_id, (time.monotonic() - t0) * 1000,
    )
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

    voice_event = voice_log.log_event(
        transcript=transcript,
        parsed={**parsed, "room": room, "patient_id": patient_id, "priority_hint": priority},
        source="audio" if not body.get("transcript") else "transcript",
        requested_by=requested_by,
        endpoint="/api/voice/urgent",
        linked_page_id=page_id,
    )

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
        "voice_event_id": voice_event["id"],
        "voice_summary": voice_event["summary"],
    }
    state.PAGES[page_id] = page

    doc = state.DOCTORS.get(doctor_id, {})
    doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
    if patient_id:
        doc["active_cases"] = doc.get("active_cases", 0) + 1

    sio = current_app.socketio
    t0 = time.monotonic()
    op_listeners = _room_size(sio, "operators")
    sio.emit("doctor_paged", page, room="operators")
    _log.info(
        "voice.emit doctor_paged cid=%s page_id=%s room=operators listeners=%d ms=%.1f",
        cid, page_id, op_listeners, (time.monotonic() - t0) * 1000,
    )

    t0 = time.monotonic()
    doc_listeners = _room_size(sio, doctor_id)
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
        "voice.emit incoming_page cid=%s page_id=%s room=%s listeners=%d ms=%.1f",
        cid, page_id, doctor_id, doc_listeners, (time.monotonic() - t0) * 1000,
    )
    if doc_listeners == 0:
        _log.warning(
            "voice.emit cid=%s page_id=%s room=%s — NOBODY LISTENING",
            cid, page_id, doctor_id,
        )

    _log.info(
        "voice.urgent done cid=%s page_id=%s doctor=%s priority=%s",
        cid, page_id, doctor_id, priority,
    )
    return jsonify(page), 201


# ---------------------------------------------------------------------------
# Voice event log — read endpoints (consumed by agents + dashboards)
# ---------------------------------------------------------------------------

@bp.get("/api/voice/log")
def voice_log_list():
    """
    List voice events, newest first. Query params:
      limit         (default 50, max 500)
      channel       filter by channel (e.g. requested_by id)
      room          filter by detected room
      since_minutes only events newer than N minutes ago
    """
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
    except ValueError:
        limit = 50
    channel = request.args.get("channel") or None
    room = request.args.get("room") or None
    since = request.args.get("since_minutes")
    try:
        since_minutes = int(since) if since is not None else None
    except ValueError:
        since_minutes = None

    events = voice_log.recent_events(
        limit=limit,
        channel=channel,
        room=room,
        since_minutes=since_minutes,
    )
    return jsonify({"events": events, "count": len(events)})


@bp.get("/api/voice/log/recent")
def voice_log_recent():
    """Convenience endpoint — last 10 minutes of voice activity."""
    minutes = int(request.args.get("minutes", 10))
    events = voice_log.recent_events(limit=200, since_minutes=minutes)
    return jsonify({
        "events": events,
        "count": len(events),
        "window_minutes": minutes,
    })


@bp.get("/api/voice/log/<event_id>")
def voice_log_get(event_id: str):
    event = voice_log.get_event(event_id)
    if not event:
        return jsonify({"error": "not_found", "id": event_id}), 404
    return jsonify(event)


@bp.get("/api/voice/channels")
def voice_log_channels():
    """All voice channels with event counts and last-seen timestamps."""
    return jsonify({"channels": voice_log.list_channels()})


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
