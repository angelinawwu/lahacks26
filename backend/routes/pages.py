from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("pages", __name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    sio.emit("doctor_paged", page, room="operators")

    # Notify the individual doctor
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

    return jsonify(page), 201


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

    # On accept: trigger the Operator Agent's Brief skill in the background.
    if outcome == "accept":
        try:
            sio.start_background_task(_generate_and_deliver_brief, page)
        except Exception as e:
            current_app.logger.warning(f"brief task spawn failed: {e}")

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
