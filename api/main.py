# hello

"""
HTTP + Socket.IO API for the MedPage agents.

Run from repo root:
  uvicorn api.main:asgi_app --reload --port 8000

The Socket.IO server shares the FastAPI port via the ASGI wrapper so the
Next.js frontend can hit `/dispatch`, `/clinicians`, and the realtime
namespace at the same origin.
"""
from __future__ import annotations

import os
import sys
import logging
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

from agents.models import AlertMessage, DispatchDecision  # noqa: E402
from agents.operator_agent import process_alert  # noqa: E402
from agents.case_handler import DB_PATH  # noqa: E402
from tinydb import TinyDB  # noqa: E402

_log = logging.getLogger("medpage.api")

app = FastAPI(title="MedPage API", version="0.2.0")

_cors = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://18.145.218.29,http://18.145.218.29:3000",
).split(",")
_cors_list = [o.strip() for o in _cors if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

# --------------------------------------------------------------------------- #
# In-memory state (hackathon scope; resets on restart)                        #
# --------------------------------------------------------------------------- #
STATE: Dict[str, Dict[str, Any]] = {
    "active_cases": {},   # alert_id -> dict
    "clinicians": {},     # clinician_id -> dict (mirrors TinyDB on startup)
}


def _model_dump(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_model_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _model_dump(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return _model_dump(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):
        return _model_dump(obj.dict())
    return obj


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_clinicians() -> None:
    db = TinyDB(DB_PATH)
    STATE["clinicians"] = {c["id"]: dict(c) for c in db.all()}


def _seed_example_alerts() -> None:
    # Simple demo alerts spanning different floors/wings.
    now = _now_iso()
    demo = [
        {
            "alert_id": "demo-001",
            "title": "Chest pain in ER",
            "room": "er",
            "priority": "P2",
            "assigned_clinician_id": "dr_chen",
            "assigned_clinician_name": "Dr. Sarah Chen",
            "specialty": ["cardiology"],
            "status": "paging",
            "created_at": now,
            "ack_deadline_seconds": 120,
            "reasoning": "Potential cardiac event; cardiology needed.",
            "guardrail_flags": [],
        },
        {
            "alert_id": "demo-002",
            "title": "Post-op pain in ICU",
            "room": "icu",
            "priority": "P1",
            "assigned_clinician_id": "dr_rodriguez",
            "assigned_clinician_name": "Dr. Miguel Rodriguez",
            "specialty": ["cardiology", "internal_medicine"],
            "status": "en_route",
            "created_at": now,
            "ack_deadline_seconds": 90,
            "reasoning": "Critical post-op monitoring required.",
            "guardrail_flags": [],
        },
        {
            "alert_id": "demo-003",
            "title": "Labor progression check",
            "room": "labor_delivery",
            "priority": "P3",
            "assigned_clinician_id": "dr_goldberg",
            "assigned_clinician_name": "Dr. Ethan Goldberg",
            "specialty": ["obstetrics", "gynecology"],
            "status": "accepted",
            "created_at": now,
            "ack_deadline_seconds": 180,
            "reasoning": "Routine L&D progression assessment.",
            "guardrail_flags": [],
        },
        {
            "alert_id": "demo-004",
            "title": "NICU desaturation",
            "room": "nicu",
            "priority": "P1",
            "assigned_clinician_id": "dr_park",
            "assigned_clinician_name": "Dr. Julia Park",
            "specialty": ["neonatology"],
            "status": "paging",
            "created_at": now,
            "ack_deadline_seconds": 60,
            "reasoning": "Neonate oxygen saturation dropped.",
            "guardrail_flags": [],
        },
        {
            "alert_id": "demo-005",
            "title": "Fall in orthopaedic wing",
            "room": "ortho_unit",
            "priority": "P2",
            "assigned_clinician_id": "dr_robinson",
            "assigned_clinician_name": "Dr. Thomas Robinson",
            "specialty": ["orthopaedics"],
            "status": "en_route",
            "created_at": now,
            "ack_deadline_seconds": 120,
            "reasoning": "Patient fall; orthopaedic evaluation needed.",
            "guardrail_flags": [],
        },
    ]
    for a in demo:
        STATE["active_cases"][a["alert_id"]] = a


@app.on_event("startup")
async def _on_startup() -> None:
    _seed_clinicians()
    _seed_example_alerts()
    _log.info(
        "MedPage API ready (clinicians=%d, alerts=%d)",
        len(STATE["clinicians"]),
        len(STATE["active_cases"]),
    )


# --------------------------------------------------------------------------- #
# REST                                                                         #
# --------------------------------------------------------------------------- #
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/clinicians")
def list_clinicians() -> list[dict[str, Any]]:
    db = TinyDB(DB_PATH)
    items = list(db.all())
    # keep STATE fresh in case TinyDB was edited
    for c in items:
        STATE["clinicians"][c["id"]] = dict(c)
    return items


@app.get("/active-cases")
def list_active_cases() -> list[dict[str, Any]]:
    return list(STATE["active_cases"].values())


@app.post("/dispatch", response_model=DispatchOut)
async def dispatch(alert: AlertIn) -> DispatchOut:
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


# --------------------------------------------------------------------------- #
# Realtime emit helpers                                                        #
# --------------------------------------------------------------------------- #
def _title_for(alert: AlertMessage) -> str:
    text = (alert.raw_text or "").strip()
    snippet = text.split(".")[0].strip() or "Alert"
    if alert.room:
        return f"{snippet[:48]} — {alert.room}"
    return snippet[:60]


async def _emit_dispatch_from_decision(
    alert: AlertMessage,
    decision: DispatchDecision,
) -> Dict[str, Any]:
    alert_id = uuid4().hex
    created_at = _now_iso()

    record = {
        "alert_id": alert_id,
        "title": _title_for(alert),
        "room": alert.room,
        "priority": decision.priority,
        "assigned_clinician_id": decision.selected_clinician_id,
        "assigned_clinician_name": decision.selected_clinician_name,
        "specialty": decision.details.get("specialty_query", []),
        "status": "paging" if decision.selected_clinician_id else "queued",
        "created_at": created_at,
        "ack_deadline_seconds": 60,
        "reasoning": decision.reasoning,
        "guardrail_flags": decision.guardrail_flags,
        "needs_operator_review": decision.needs_operator_review,
        "ehr_matched": decision.ehr_matched,
        "time_queued": decision.time_queued,
        "autonomy_mode": decision.autonomy_mode,
        "mode": decision.mode,
    }
    STATE["active_cases"][alert_id] = record

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

    await sio.emit("alert_created", record, room="operators")
    await sio.emit(
        "dispatch_decision",
        {"alert_id": alert_id, "priority": pr_dump, "case": case_dump},
        room="operators",
    )
    if decision.selected_clinician_id:
        await sio.emit(
            "incoming_page",
            {
                "alert_id": alert_id,
                "title": record["title"],
                "room": alert.room,
                "priority": decision.priority,
                "reasoning": decision.reasoning,
                "created_at": created_at,
                "ack_deadline_seconds": 60,
            },
            room=decision.selected_clinician_id,
        )

    return {"alert_id": alert_id, "priority": pr_dump, "case": case_dump}


# --------------------------------------------------------------------------- #
# Socket.IO handlers                                                           #
# --------------------------------------------------------------------------- #
@sio.event
async def connect(sid: str, environ: Dict[str, Any], auth: Optional[Dict[str, Any]] = None) -> None:
    auth = auth or {}
    role = auth.get("role")
    clinician_id = auth.get("clinician_id")
    if role == "operator":
        await sio.enter_room(sid, "operators")
        _log.info("operator connected sid=%s", sid)
        # bootstrap snapshot
        await sio.emit(
            "snapshot",
            {
                "active_cases": list(STATE["active_cases"].values()),
                "clinicians": list(STATE["clinicians"].values()),
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
    alert_id = data.get("alert_id")
    clinician_id = data.get("clinician_id")
    response = data.get("response")
    case = STATE["active_cases"].get(alert_id)
    if not case:
        return
    if response == "accept":
        case["status"] = "accepted"
        case["responded_at"] = _now_iso()
        await sio.emit("alert_updated", case, room="operators")
        await sio.emit(
            "page_resolved",
            {"alert_id": alert_id, "outcome": "accepted"},
            room=clinician_id,
        )
    elif response == "decline":
        case["status"] = "declined"
        case["responded_at"] = _now_iso()
        await sio.emit("alert_updated", case, room="operators")
        await sio.emit(
            "page_resolved",
            {"alert_id": alert_id, "outcome": "declined"},
            room=clinician_id,
        )


@sio.on("status_update")
async def on_status_update(sid: str, data: Dict[str, Any]) -> None:
    clinician_id = data.get("clinician_id")
    status = data.get("status")
    if not clinician_id or not status:
        return
    record = STATE["clinicians"].get(clinician_id, {"id": clinician_id})
    record["status"] = status
    if "zone" in data:
        record["zone"] = data["zone"]
    STATE["clinicians"][clinician_id] = record
    await sio.emit(
        "clinician_status_changed",
        {"clinician_id": clinician_id, "status": status, "zone": record.get("zone")},
        room="operators",
    )
