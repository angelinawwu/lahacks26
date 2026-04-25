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
        "status": "paging",
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
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

    current_app.socketio.emit("page_response", page, room="operators")
    return jsonify(page)
