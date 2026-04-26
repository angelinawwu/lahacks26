"""
Core entity routes: doctors, nurses, patients, rooms, map.
Replaces backend/routes/doctors.py, nurses.py, patients.py, rooms.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api import shared_state as state
from api.sio import sio

router = APIRouter()


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------

@router.get("/api/doctors")
def list_doctors():
    return list(state.DOCTORS.values())


@router.get("/api/doctors/{doctor_id}")
def get_doctor(doctor_id: str):
    doc = state.DOCTORS.get(doctor_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    return doc


@router.patch("/api/doctors/{doctor_id}/status")
async def update_doctor_status(doctor_id: str, request: Request):
    """Update a doctor's live status/zone/on_call and notify operators."""
    doc = state.DOCTORS.get(doctor_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    body = await request.json()
    if "status" in body:
        doc["status"] = body["status"]
    if "zone" in body:
        doc["zone"] = body["zone"]
    if "on_call" in body:
        doc["on_call"] = body["on_call"]
    await sio.emit("doctor_status_changed", {"id": doctor_id, **doc}, room="operators")
    return doc


# ---------------------------------------------------------------------------
# Nurses
# ---------------------------------------------------------------------------

@router.get("/api/nurses")
def list_nurses():
    return list(state.NURSES.values())


@router.get("/api/nurses/{nurse_id}")
def get_nurse(nurse_id: str):
    nurse = state.NURSES.get(nurse_id)
    if not nurse:
        raise HTTPException(status_code=404, detail=f"nurse {nurse_id} not found")
    return nurse


@router.patch("/api/nurses/{nurse_id}/status")
async def update_nurse_status(nurse_id: str, request: Request):
    nurse = state.NURSES.get(nurse_id)
    if not nurse:
        raise HTTPException(status_code=404, detail=f"nurse {nurse_id} not found")
    body = await request.json()
    if "status" in body:
        nurse["status"] = body["status"]
    if "zone" in body:
        nurse["zone"] = body["zone"]
    await sio.emit("nurse_status_changed", {"id": nurse_id, **nurse}, room="operators")
    return nurse


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@router.get("/api/patients")
def list_patients():
    return list(state.PATIENTS.values())


@router.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    patient = state.PATIENTS.get(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"patient {patient_id} not found")
    ehr = state.EHR.get(patient_id, {})
    return {**patient, "ehr": ehr}


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

@router.get("/api/rooms")
def list_rooms():
    return list(state.ROOMS.values())


@router.get("/api/rooms/{room_id}")
def get_room(room_id: str):
    room = state.ROOMS.get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"room {room_id} not found")
    patient = None
    if room.get("current_patient_id"):
        patient = state.PATIENTS.get(room["current_patient_id"])
    return {**room, "patient": patient}


@router.get("/api/map")
def get_map():
    """Rooms grouped by floor for floor-map rendering."""
    floors: dict = {}
    for room in state.ROOMS.values():
        key = str(room["floor"])
        floors.setdefault(key, []).append(room)
    for key in floors:
        floors[key].sort(key=lambda r: (r.get("y", 0), r.get("x", 0)))
    return {"floors": floors}
