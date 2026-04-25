from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("doctors", __name__)


@bp.get("/api/doctors")
def list_doctors():
    """Return all doctors with their live status."""
    return jsonify(list(state.DOCTORS.values()))


@bp.get("/api/doctors/<doctor_id>")
def get_doctor(doctor_id):
    doc = state.DOCTORS.get(doctor_id)
    if not doc:
        return jsonify({"error": "doctor not found", "id": doctor_id}), 404
    return jsonify(doc)


@bp.patch("/api/doctors/<doctor_id>/status")
def update_doctor_status(doctor_id):
    """
    Update a doctor's status and/or zone.
    Body: { "status": "available", "zone": "icu", "on_call": true }
    Emits doctor_status_changed to the operators Socket.IO room.
    """
    doc = state.DOCTORS.get(doctor_id)
    if not doc:
        return jsonify({"error": "doctor not found", "id": doctor_id}), 404

    body = request.get_json(silent=True) or {}
    if "status" in body:
        doc["status"] = body["status"]
    if "zone" in body:
        doc["zone"] = body["zone"]
    if "on_call" in body:
        doc["on_call"] = body["on_call"]

    current_app.socketio.emit(
        "doctor_status_changed",
        {"id": doctor_id, **doc},
        room="operators",
    )
    return jsonify(doc)
