"""
Unified HTTP + Socket.IO backend for MedPage.

Merges the old FastAPI (api/main.py, port 8000) and Flask (backend/app.py, port 8001)
into a single ASGI server on port 8001.

Run from repo root:
  uvicorn api.main:asgi_app --reload --port 8001

TinyDB is the canonical store for clinicians (db/clinicians.json) and
pages (db/pages.json). Doctors/patients/rooms/EHR are seeded in-memory
from backend/data/*.json and reset on restart.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import the shared Socket.IO instance (avoids circular imports in routes).
from api.sio import sio  # noqa: E402

# Unified state — seeded on startup.
from api import shared_state  # noqa: E402

# Route modules (converted from Flask blueprints).
from api.routes.core import router as core_router  # noqa: E402
from api.routes.pages import router as pages_router  # noqa: E402
from api.routes.proactive import router as proactive_router  # noqa: E402
from api.routes.ehr import router as ehr_router  # noqa: E402
from api.routes.voice import router as voice_router  # noqa: E402
from api.routes.settings import router as settings_router  # noqa: E402

from agents.models import AlertMessage, DispatchDecision  # noqa: E402

try:
    from agents.operator_agent import process_alert  # noqa: E402
except Exception as _exc:
    process_alert = None  # type: ignore[assignment]
    logging.getLogger("medpage.api").warning(
        "operator_agent unavailable — /dispatch disabled (%s)", _exc,
    )

_log = logging.getLogger("medpage.api")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="MedPage API", version="0.3.0")

_cors_env = os.getenv("CORS_ORIGINS", "")
_cors = [o.strip() for o in _cors_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors if _cors else ["*"],
    allow_credentials=bool(_cors),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all domain routers.
app.include_router(core_router)
app.include_router(pages_router)
app.include_router(proactive_router)
app.include_router(ehr_router)
app.include_router(voice_router)
app.include_router(settings_router)

# ASGI wrapper exposes both FastAPI REST and Socket.IO on the same port.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _on_startup() -> None:
    shared_state.seed()
    _log.info(
        "MedPage unified API ready — clinicians=%d doctors=%d pages=%d",
        len(shared_state.CLINICIANS),
        len(shared_state.DOCTORS),
        len(shared_state.PAGES),
    )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title_for(alert: AlertMessage) -> str:
    text = (alert.raw_text or "").strip()
    snippet = text.split(".")[0].strip() or "Alert"
    if alert.room:
        return f"{snippet[:48]} — {alert.room}"
    return snippet[:60]


# ---------------------------------------------------------------------------
# REST — clinician roster (TinyDB canonical)
# ---------------------------------------------------------------------------
class ClinicianPatchIn(BaseModel):
    on_call: Optional[bool] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    status: Optional[str] = None
    zone: Optional[str] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_CLINICIANS_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db",
    "clinicians.json",
)


@app.get("/clinicians")
def list_clinicians() -> list[dict[str, Any]]:
    """Return the TinyDB clinician roster, keeping shared_state in sync."""
    from tinydb import TinyDB
    db = TinyDB(_CLINICIANS_DB_PATH)
    items = list(db.all())
    for c in items:
        shared_state.CLINICIANS[c["id"]] = dict(c)
    return items


@app.patch("/clinicians/{clinician_id}")
async def patch_clinician(clinician_id: str, body: ClinicianPatchIn) -> dict[str, Any]:
    """Patch a clinician in TinyDB + shared_state and notify operators."""
    from tinydb import Query, TinyDB
    db = TinyDB(_CLINICIANS_DB_PATH)
    Q = Query()
    found = db.search(Q.id == clinician_id)
    if not found:
        return {"error": "clinician not found", "id": clinician_id}

    record = dict(found[0])
    updates: Dict[str, Any] = {}
    for field in ("on_call", "shift_start", "shift_end", "status", "zone"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val
            record[field] = val

    if updates:
        db.update(updates, Q.id == clinician_id)
        shared_state.CLINICIANS[clinician_id] = record
        # Keep DOCTORS in sync so snapshot stays consistent.
        if clinician_id in shared_state.DOCTORS:
            shared_state.DOCTORS[clinician_id].update(
                {k: v for k, v in updates.items() if k in shared_state.DOCTORS[clinician_id]}
            )
        payload = {
            "clinician_id": clinician_id,
            "id": clinician_id,            # doctor_status_changed listeners use `id`
            "status": record.get("status"),
            "zone": record.get("zone"),
            "on_call": record.get("on_call"),
            "shift_start": record.get("shift_start"),
            "shift_end": record.get("shift_end"),
        }
        await sio.emit("clinician_status_changed", payload, room="operators")
        await sio.emit("doctor_status_changed", payload, room="operators")
    return record


# ---------------------------------------------------------------------------
# REST — patient search
# ---------------------------------------------------------------------------
@app.get("/api/patients/search")
def search_patients(q: str = ""):
    """
    Search PATIENTS + EHR by patient ID or name (case-insensitive substring).
    Returns list of { id, name, room, primary_diagnosis, comorbidities }.
    """
    q_lower = q.strip().lower()
    results = []
    seen: set = set()
    for pid, patient in shared_state.PATIENTS.items():
        name = str(patient.get("name") or "").lower()
        if not q_lower or q_lower in pid.lower() or q_lower in name:
            ehr = shared_state.EHR.get(pid, {})
            entry = {
                "id": pid,
                "name": patient.get("name") or pid,
                "room": patient.get("room"),
                "primary_diagnosis": ehr.get("primary_diagnosis") or patient.get("primary_diagnosis"),
                "comorbidities": ehr.get("comorbidities") or patient.get("comorbidities") or [],
            }
            if pid not in seen:
                seen.add(pid)
                results.append(entry)
    # Also search EHR-only records
    for pid, ehr in shared_state.EHR.items():
        if pid in seen:
            continue
        name = str(ehr.get("name") or "").lower()
        patient_id_field = str(ehr.get("patient_id") or pid).lower()
        if not q_lower or q_lower in pid.lower() or q_lower in name or q_lower in patient_id_field:
            results.append({
                "id": pid,
                "name": ehr.get("name") or pid,
                "room": ehr.get("room"),
                "primary_diagnosis": ehr.get("primary_diagnosis"),
                "comorbidities": ehr.get("comorbidities") or [],
            })
    return {"results": results[:20]}


# ---------------------------------------------------------------------------
# REST — dispatch (AI agent pipeline)
# ---------------------------------------------------------------------------
class AlertIn(BaseModel):
    raw_text: str
    room: Optional[str] = None
    specialty_hint: Optional[str] = None
    symptoms: Optional[str] = None
    patient_id: Optional[str] = None
    mode: Optional[str] = None
    requested_by: Optional[str] = None


class DispatchOut(BaseModel):
    alert_id: str
    priority: dict
    case: dict


@app.post("/dispatch", response_model=DispatchOut)
async def dispatch(alert: AlertIn) -> DispatchOut:
    if process_alert is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="agent stack unavailable")
    msg = AlertMessage(
        raw_text=alert.raw_text,
        room=alert.room,
        specialty_hint=alert.specialty_hint,
        symptoms=alert.symptoms,
        patient_id=alert.patient_id,
        mode=alert.mode,
        requested_by=alert.requested_by,
    )
    decision: DispatchDecision = await process_alert(msg)
    out = await _emit_dispatch_from_decision(msg, decision)
    return DispatchOut(alert_id=out["alert_id"], priority=out["priority"], case=out["case"])


async def _emit_dispatch_from_decision(
    alert: AlertMessage,
    decision: DispatchDecision,
) -> Dict[str, Any]:
    """Store dispatch result in shared_state.PAGES (TinyDB) and emit socket events."""
    alert_id = uuid4().hex
    created_at = _now_iso()

    # Determine if manual mode is active — pages are held for operator approval.
    manual_mode = shared_state.PAGING_MODES.get("global_mode") == "manual"

    if manual_mode:
        page_status = "pending_approval"
    elif decision.selected_clinician_id:
        page_status = "paging"
    else:
        page_status = "queued"

    # Normalise to page format so queue/list endpoints work seamlessly.
    page_record = {
        "id": alert_id,
        "alert_id": alert_id,           # keep for backward compat
        "source": "dispatch",
        "doctor_id": decision.selected_clinician_id,
        "patient_id": alert.patient_id,
        "message": alert.raw_text,
        "room": alert.room,
        "priority": decision.priority,
        "status": page_status,
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
        "escalation_history": [],
        "backup_doctors": decision.backup_clinician_ids,
        # dispatch-specific metadata
        "title": _title_for(alert),
        "assigned_clinician_name": decision.selected_clinician_name,
        "specialty": decision.details.get("specialty_query", []),
        "ack_deadline_seconds": 60,
        "reasoning": decision.reasoning,
        "guardrail_flags": decision.guardrail_flags,
        "needs_operator_review": decision.needs_operator_review or manual_mode,
        "ehr_matched": decision.ehr_matched,
        "autonomy_mode": decision.autonomy_mode,
        "mode": decision.mode,
    }
    # Persist to TinyDB + in-memory
    shared_state.save_page(page_record)

    pr_dump = {
        "priority": decision.priority,
        "guardrail_flags": decision.guardrail_flags,
        "reasoning": decision.details.get("priority_handler_reasoning", decision.reasoning),
        "fallback_used": False,
    }
    case_dump = {
        "candidates": [],
        "specialty_query": decision.details.get("specialty_query", []),
        "total_available": decision.details.get("candidates_count", 0),
        "reasoning": decision.details.get("case_handler_reasoning", decision.reasoning),
        "fallback_used": False,
    }

    if manual_mode:
        # Hold for operator review — emit pending event instead of paging doctor.
        await sio.emit("page_pending_approval", page_record, room="operators")
    else:
        await sio.emit("alert_created", page_record, room="operators")
        await sio.emit(
            "dispatch_decision",
            {"alert_id": alert_id, "priority": pr_dump, "case": case_dump},
            room="operators",
        )
        if decision.selected_clinician_id:
            await sio.emit(
                "incoming_page",
                {
                    "page_id": alert_id,
                    "alert_id": alert_id,
                    "title": page_record["title"],
                    "room": alert.room,
                    "priority": decision.priority,
                    "reasoning": decision.reasoning,
                    "created_at": created_at,
                    "ack_deadline_seconds": 60,
                },
                room=decision.selected_clinician_id,
            )

    return {"alert_id": alert_id, "priority": pr_dump, "case": case_dump}


# ---------------------------------------------------------------------------
# Socket.IO event handlers (merged from both old servers)
# ---------------------------------------------------------------------------
@sio.event
async def connect(sid: str, environ: Dict[str, Any], auth: Optional[Dict[str, Any]] = None) -> None:
    auth = auth or {}
    role = auth.get("role")
    clinician_id = auth.get("clinician_id")

    if role == "operator":
        await sio.enter_room(sid, "operators")
        _log.info("operator connected sid=%s", sid)
        active_pages = [
            p for p in shared_state.PAGES.values()
            if p.get("status") in ("paging", "pending", "escalated", "queued")
        ]
        await sio.emit(
            "snapshot",
            {
                # New-style fields (Flask origin)
                "doctors": list(shared_state.DOCTORS.values()),
                "nurses": list(shared_state.NURSES.values()),
                "patients": list(shared_state.PATIENTS.values()),
                "rooms": list(shared_state.ROOMS.values()),
                "active_pages": active_pages,
                # Legacy fields (FastAPI origin) — kept for backward compat
                "active_cases": active_pages,
                "clinicians": list(shared_state.CLINICIANS.values()),
            },
            to=sid,
        )

    if clinician_id:
        await sio.enter_room(sid, clinician_id)
        _log.info("clinician %s connected sid=%s", clinician_id, sid)


@sio.event
async def disconnect(sid: str) -> None:
    _log.info("disconnect sid=%s", sid)


@sio.on("page_response")
async def on_page_response(sid: str, data: Dict[str, Any]) -> None:
    """Socket-based page response (legacy path; REST /api/page/<id>/respond preferred)."""
    alert_id = data.get("alert_id") or data.get("page_id")
    clinician_id = data.get("clinician_id")
    response = data.get("response")
    page = shared_state.PAGES.get(alert_id)
    if not page:
        return
    outcome = "accept" if response == "accept" else "decline"
    page["outcome"] = outcome
    page["status"] = "accepted" if outcome == "accept" else "declined"
    page["responded_at"] = _now_iso()
    shared_state.save_page(page)
    await sio.emit("alert_updated", page, room="operators")
    await sio.emit(
        "page_resolved",
        {"alert_id": alert_id, "page_id": alert_id, "outcome": outcome},
        room=clinician_id,
    )


@sio.on("status_update")
async def on_status_update(sid: str, data: Dict[str, Any]) -> None:
    """Socket-based status update for clinicians."""
    clinician_id = data.get("clinician_id")
    status = data.get("status")
    if not clinician_id or not status:
        return
    # Update both stores
    if clinician_id in shared_state.CLINICIANS:
        shared_state.CLINICIANS[clinician_id]["status"] = status
        if "zone" in data:
            shared_state.CLINICIANS[clinician_id]["zone"] = data["zone"]
    if clinician_id in shared_state.DOCTORS:
        shared_state.DOCTORS[clinician_id]["status"] = status
        if "zone" in data:
            shared_state.DOCTORS[clinician_id]["zone"] = data["zone"]
    event_payload = {
        "clinician_id": clinician_id,
        "id": clinician_id,    # doctor_status_changed listeners use `id`
        "status": status,
        "zone": data.get("zone"),
    }
    await sio.emit("clinician_status_changed", event_payload, room="operators")
    # Also emit doctor_status_changed so ClinicianDirectory picks up self-updates.
    await sio.emit("doctor_status_changed", event_payload, room="operators")
