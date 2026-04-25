from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("nurses", __name__)


@bp.get("/api/nurses")
def list_nurses():
    return jsonify(list(state.NURSES.values()))


@bp.get("/api/nurses/<nurse_id>")
def get_nurse(nurse_id):
    nurse = state.NURSES.get(nurse_id)
    if not nurse:
        return jsonify({"error": "nurse not found", "id": nurse_id}), 404
    return jsonify(nurse)


@bp.patch("/api/nurses/<nurse_id>/status")
def update_nurse_status(nurse_id):
    """Update a nurse's status and/or zone."""
    nurse = state.NURSES.get(nurse_id)
    if not nurse:
        return jsonify({"error": "nurse not found", "id": nurse_id}), 404

    body = request.get_json(silent=True) or {}
    if "status" in body:
        nurse["status"] = body["status"]
    if "zone" in body:
        nurse["zone"] = body["zone"]

    current_app.socketio.emit(
        "nurse_status_changed",
        {"id": nurse_id, **nurse},
        room="operators",
    )
    return jsonify(nurse)
