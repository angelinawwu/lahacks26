from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import requests
from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("pages", __name__)
_log = logging.getLogger("medpage.pages")

# FastAPI host that owns the agent dispatch pipeline (`/api/page-request`,
# `/dispatch`). Flask proxies those routes there so the operator UI keeps
# hitting a single origin (Flask :8001) without duplicating agent code.
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8000").rstrip("/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _room_size(sio, room: str, namespace: str = "/") -> int:
    """Count Socket.IO sessions joined to `room`. -1 if unknown."""
    try:
        ns_rooms = sio.server.manager.rooms.get(namespace, {})
        members = ns_rooms.get(room) or {}
        return len(members)
    except Exception:
        return -1


def _cid() -> str:
    """Use the X-Correlation-Id from the caller (e.g. operator_agent) or
    fall back to a fresh 8-char hex so every page leaves one greppable trace."""
    incoming = request.headers.get("X-Correlation-Id")
    if incoming:
        return incoming.strip()[:32]
    return uuid4().hex[:8]


@bp.get("/api/pages")
def list_pages():
    """Return all pages (history + active)."""
    return jsonify(list(state.PAGES.values()))


@bp.get("/api/pages/<page_id>")
def get_page(page_id):
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404
    return jsonify(page)


@bp.post("/api/page")
def create_page():
    """
    Trigger a page to a doctor. Called by the AI agent.

    Required body fields:
      doctor_id  — ID of the doctor to page

    Optional:
      patient_id    — patient associated with this page
      message       — free-text message for the doctor
      priority      — "P1" | "P2" | "P3" | "P4" (default "P2")
      room          — room identifier or name
      requested_by  — operator / nurse ID who requested the page
      backup_doctors — list of backup doctor IDs for escalation

    Side effects:
      - Creates a page record in state.PAGES
      - Increments doctor's page_count_1hr
      - Emits `doctor_paged`  → operators Socket.IO room
      - Emits `incoming_page` → individual doctor Socket.IO room
    """
    body = request.get_json(silent=True) or {}

    doctor_id = body.get("doctor_id")
    if not doctor_id:
        return jsonify({"error": "doctor_id is required"}), 400

    patient_id = body.get("patient_id")
    message = body.get("message", "")
    priority = body.get("priority", "P2")
    room = body.get("room")
    requested_by = body.get("requested_by")
    backup_doctors = body.get("backup_doctors", [])

    page_id = uuid4().hex
    created_at = _now()
    cid = _cid()

    _log.info(
        "page.create start cid=%s page_id=%s doctor_id=%s priority=%s room=%s requested_by=%s",
        cid, page_id, doctor_id, priority, room, requested_by,
    )

    if doctor_id not in state.DOCTORS:
        _log.warning(
            "page.create cid=%s doctor_id=%s NOT in DOCTORS dict — page will be emitted to an empty room",
            cid, doctor_id,
        )

    page = {
        "id": page_id,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "message": message,
        "priority": priority,
        "room": room,
        "requested_by": requested_by,
        "backup_doctors": backup_doctors,
        "status": "paging",
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
        "escalation_history": [],
    }
    state.PAGES[page_id] = page

    # Keep doctor stats current
    doc = state.DOCTORS.get(doctor_id)
    if doc:
        doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
        if patient_id:
            doc["active_cases"] = doc.get("active_cases", 0) + 1

    sio = current_app.socketio

    # Notify the operator dashboard
    t0 = time.monotonic()
    op_listeners = _room_size(sio, "operators")
    sio.emit("doctor_paged", page, room="operators")
    _log.info(
        "page.emit doctor_paged cid=%s page_id=%s room=operators listeners=%d ms=%.1f",
        cid, page_id, op_listeners, (time.monotonic() - t0) * 1000,
    )

    # Notify the individual doctor
    t0 = time.monotonic()
    doc_listeners = _room_size(sio, doctor_id)
    sio.emit(
        "incoming_page",
        {
            "page_id": page_id,
            "message": message,
            "patient_id": patient_id,
            "room": room,
            "priority": priority,
            "created_at": created_at,
            "ack_deadline_seconds": 60,
        },
        room=doctor_id,
    )
    _log.info(
        "page.emit incoming_page cid=%s page_id=%s room=%s listeners=%d ms=%.1f",
        cid, page_id, doctor_id, doc_listeners, (time.monotonic() - t0) * 1000,
    )
    if doc_listeners == 0:
        _log.warning(
            "page.emit cid=%s page_id=%s room=%s — NOBODY LISTENING (clinician not connected or room name mismatch)",
            cid, page_id, doctor_id,
        )

    return jsonify(page), 201


@bp.post("/api/page-request")
def proxy_page_request():
    """Proxy to FastAPI's `/api/page-request` so the agent dispatch pipeline
    (priority handler + case handler) handles operator-submitted requests.

    Flask doesn't own that pipeline — replicating it here would mean copying
    the EHR enrichment, scheduling, and process_alert glue. Forwarding keeps
    the Flask origin (where CORS already lives) as the single endpoint the
    frontend talks to.
    """
    body = request.get_json(silent=True) or {}
    try:
        r = requests.post(
            f"{FASTAPI_URL}/api/page-request",
            json=body,
            timeout=10,
        )
    except requests.RequestException as e:
        _log.error("page-request proxy: upstream unreachable: %s", e)
        return jsonify({"error": "agent backend unreachable", "detail": str(e)}), 502

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "non-json upstream response", "body": r.text}
    return jsonify(payload), r.status_code


@bp.post("/api/clinician/<clinician_id>/repage")
def repage_clinician(clinician_id):
    """Re-emit `incoming_page` for every page assigned to this clinician
    whose status is still unaccepted (paging / pending / escalated).

    Triggered when the operator clicks a clinician's name on the floor map —
    it does NOT create a new page, it just re-pops the existing ones on the
    clinician's screen so they can't be missed.
    """
    pending = [
        p for p in state.PAGES.values()
        if p.get("doctor_id") == clinician_id
        and p.get("status") in ("paging", "pending", "escalated")
    ]
    pending.sort(key=lambda p: p.get("created_at") or "")

    sio = current_app.socketio
    cid = _cid()
    listeners = _room_size(sio, clinician_id)

    for p in pending:
        sio.emit(
            "incoming_page",
            {
                "page_id": p["id"],
                "message": p.get("message", ""),
                "patient_id": p.get("patient_id"),
                "room": p.get("room"),
                "priority": p.get("priority"),
                "created_at": p.get("created_at"),
                "ack_deadline_seconds": p.get("ack_deadline_seconds", 60),
            },
            room=clinician_id,
        )

    _log.info(
        "page.repage cid=%s clinician=%s count=%d listeners=%d",
        cid, clinician_id, len(pending), listeners,
    )
    return jsonify({
        "clinician_id": clinician_id,
        "repaged": len(pending),
        "page_ids": [p["id"] for p in pending],
        "listeners": listeners,
    })


@bp.post("/api/page/<page_id>/respond")
def respond_to_page(page_id):
    """
    Record a doctor's response to a page.

    Body: { "outcome": "accept" | "decline" }

    Side effects:
      - Updates page record status
      - Emits `page_response` → operators Socket.IO room
      - On 'accept': spawns the Operator Agent's Brief skill in a background
        thread and forwards the resulting SBAR brief to the clinician.
    """
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404

    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("accept", "decline"):
        return jsonify({"error": "outcome must be 'accept' or 'decline'"}), 400

    page["outcome"] = outcome
    page["status"] = "accepted" if outcome == "accept" else "declined"
    page["responded_at"] = _now()

    sio = current_app.socketio
    sio.emit("page_response", page, room="operators")

    # Reflect the doctor's accepted assignment in their live status so the
    # operator dashboard sees them transition out of the available pool. The
    # symmetric flip back to "available" happens in /api/page/<id>/resolve.
    if outcome == "accept":
        doc = state.DOCTORS.get(page.get("doctor_id"))
        if doc:
            doc["status"] = "on_case"
            sio.emit("doctor_status_changed", {"id": doc["id"], **doc}, room="operators")

    # On accept: trigger the Operator Agent's Brief skill in the background.
    if outcome == "accept":
        try:
            sio.start_background_task(_generate_and_deliver_brief, page)
        except Exception as e:
            current_app.logger.warning(f"brief task spawn failed: {e}")

    return jsonify(page)


@bp.post("/api/page/<page_id>/resolve")
def resolve_page(page_id):
    """
    Mark a page as resolved (the doctor finished the case).

    Side effects:
      - Updates page record: status="resolved", outcome="resolved",
        resolved_at=<now>
      - Flips the doctor's status back to "available" and decrements
        active_cases (floor 0)
      - Emits `page_response`           → operators room (page row)
      - Emits `page_resolved`           → clinician room (lightweight payload)
      - Emits `doctor_status_changed`   → operators room
    """
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404

    if page.get("status") == "resolved":
        return jsonify(page)

    page["status"] = "resolved"
    page["outcome"] = "resolved"
    page["resolved_at"] = _now()

    sio = current_app.socketio

    doc_id = page.get("doctor_id")
    doc = state.DOCTORS.get(doc_id) if doc_id else None
    if doc:
        doc["status"] = "available"
        doc["active_cases"] = max(0, int(doc.get("active_cases", 0)) - 1)
        sio.emit("doctor_status_changed", {"id": doc["id"], **doc}, room="operators")

    sio.emit("page_response", page, room="operators")
    if doc_id:
        sio.emit(
            "page_resolved",
            {"page_id": page_id, "alert_id": page_id, "outcome": "resolved"},
            room=doc_id,
        )

    return jsonify(page)


def _generate_and_deliver_brief(page: dict) -> None:
    """
    Run the agent's Brief skill (SBAR generator) and emit the result to the
    accepting clinician via Socket.IO. Runs in the eventlet/socketio
    background context — must NOT block the request thread.
    """
    try:
        # Local import to avoid pulling agent deps at backend boot if unused.
        from agents.skills.brief import generate_brief_sync
    except Exception as e:
        print(f"[backend] brief skill unavailable: {e}")
        return

    page_id = page.get("id", "")
    clinician_id = page.get("doctor_id", "")
    patient_id = page.get("patient_id")

    # Pull patient + EHR if known
    patient = None
    if patient_id:
        p = state.PATIENTS.get(patient_id)
        if p:
            ehr = state.EHR.get(patient_id, {}) if hasattr(state, "EHR") else {}
            patient = {**p, **(ehr or {})}

    alert = {
        "raw_text": page.get("message", ""),
        "priority": page.get("priority"),
        "room": page.get("room"),
    }
    scene = {
        "requested_by": page.get("requested_by"),
        "paged_at": page.get("created_at"),
        "responded_at": page.get("responded_at"),
        "escalated_from": (page.get("escalation_history") or [{}])[-1].get("from_doctor")
        if page.get("escalation_history") else None,
    }

    try:
        brief = generate_brief_sync(
            alert=alert,
            patient=patient,
            scene=scene,
            page_id=page_id,
            clinician_id=clinician_id,
        )
    except Exception as e:
        print(f"[backend] brief generation failed: {e}")
        return

    # Store + deliver. We import here so circular-import risk stays local.
    try:
        from routes.proactive import BRIEFS
        BRIEFS[page_id] = {
            "page_id": brief.page_id,
            "clinician_id": brief.clinician_id,
            "patient_id": brief.patient_id,
            "brief_text": brief.brief_text,
            "word_count": brief.word_count,
            "generated_at": brief.generated_at,
        }
    except Exception:
        pass

    # Forward to clinician + operators dashboard
    try:
        from flask import current_app as ca
        sio = ca.socketio  # type: ignore[attr-defined]
        payload = {
            "page_id": brief.page_id,
            "clinician_id": brief.clinician_id,
            "patient_id": brief.patient_id,
            "brief_text": brief.brief_text,
            "word_count": brief.word_count,
            "generated_at": brief.generated_at,
        }
        sio.emit("sbar_brief", payload, room=clinician_id)
        sio.emit("sbar_brief", payload, room="operators")
    except Exception as e:
        print(f"[backend] brief socket emit failed: {e}")
