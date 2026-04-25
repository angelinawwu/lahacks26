from flask import Blueprint, jsonify
import state

bp = Blueprint("rooms", __name__)


@bp.get("/api/rooms")
def list_rooms():
    """Return all rooms with location and occupancy."""
    return jsonify(list(state.ROOMS.values()))


@bp.get("/api/rooms/<room_id>")
def get_room(room_id):
    room = state.ROOMS.get(room_id)
    if not room:
        return jsonify({"error": "room not found", "id": room_id}), 404
    patient = None
    if room.get("current_patient_id"):
        patient = state.PATIENTS.get(room["current_patient_id"])
    return jsonify({**room, "patient": patient})


@bp.get("/api/map")
def get_map():
    """
    Return rooms grouped by floor for floor-map rendering.
    Response shape: { "floors": { "1": [...rooms], "2": [...rooms], ... } }
    """
    floors: dict = {}
    for room in state.ROOMS.values():
        key = str(room["floor"])
        floors.setdefault(key, []).append(room)

    # Sort rooms within each floor by y then x
    for key in floors:
        floors[key].sort(key=lambda r: (r.get("y", 0), r.get("x", 0)))

    return jsonify({"floors": floors})
