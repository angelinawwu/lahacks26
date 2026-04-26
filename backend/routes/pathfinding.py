"""
Pathfinding API for the demo.

GET /api/pathfinding?patient_zone=floor_3_corridor&specialty=cardiology
  → { assigned_doctor, path_coords, eta_minutes, all_doctors, … }

GET /demo
  → serves the standalone pathfinding demo HTML page
"""
from __future__ import annotations

import os
import sys

# Allow importing hospital_graph from the repo root's agents/ package.
# __file__ is backend/routes/pathfinding.py → go up 3 levels to repo root.
_HERE    = os.path.dirname(os.path.abspath(__file__))   # backend/routes/
_BACKEND = os.path.dirname(_HERE)                        # backend/
_REPO    = os.path.dirname(_BACKEND)                     # repo root
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from flask import Blueprint, jsonify, request, send_from_directory

from agents.hospital_graph import astar, zone_coords
import state

bp = Blueprint("pathfinding", __name__)

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")

_FLOOR_LABEL_TO_Z: dict[str, int] = {
    "A": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
}


def _doctor_floor_z(doc: dict) -> int:
    return _FLOOR_LABEL_TO_Z.get(str(doc.get("floor", "3")), 3)


@bp.get("/demo")
def demo_page():
    return send_from_directory(_STATIC, "pathfinding_demo.html")


@bp.get("/api/pathfinding")
def solve():
    patient_zone = request.args.get("patient_zone", "floor_3_corridor")
    specialty    = request.args.get("specialty", "cardiology")

    doctors = list(state.DOCTORS.values())

    best: dict | None = None
    best_score = float("-inf")
    best_path: list[str] = []
    best_cost = 0.0

    for doc in doctors:
        if doc.get("status") == "off_shift":
            continue

        doc_specialties: list[str] = doc.get("specialty", [])
        specialty_match = specialty in doc_specialties or any(
            specialty in s for s in doc_specialties
        )

        doc_zone = doc.get("zone", "floor_3_corridor")
        path, cost = astar(doc_zone, patient_zone)

        score = 0.0
        if specialty_match:
            score += 10.0
        score -= cost * 0.6
        score -= doc.get("active_cases", 0) * 0.5
        score -= doc.get("page_count_1hr", 0) * 0.3
        if doc.get("on_call"):
            score += 2.0
        if doc.get("status") == "available":
            score += 3.0
        elif doc.get("status") == "in_procedure":
            score -= 5.0

        if score > best_score:
            best_score = score
            best = doc
            best_path = path
            best_cost = cost

    # Convert path zone names → viewbox coordinates
    path_coords: list[dict] = []
    for zone_id in best_path:
        c = zone_coords(zone_id)
        if c:
            path_coords.append({
                "zone": zone_id,
                "floor_z": c[0],
                "x": float(c[1]),
                "y": float(c[2]),
            })

    # Patient position
    pc = zone_coords(patient_zone)
    patient_coords = (
        {"floor_z": pc[0], "x": float(pc[1]), "y": float(pc[2])}
        if pc else {"floor_z": 3, "x": 530.0, "y": 350.0}
    )

    # Enrich all doctors with floor_z and viewbox coords
    all_docs = []
    for doc in doctors:
        fz = _doctor_floor_z(doc)
        c = zone_coords(doc.get("zone", ""))
        all_docs.append({
            "id": doc["id"],
            "name": doc["name"],
            "specialty": doc.get("specialty", []),
            "status": doc.get("status", "available"),
            "on_call": doc.get("on_call", False),
            "zone": doc.get("zone", ""),
            "floor": doc.get("floor", "3"),
            "floor_z": fz,
            "x": float(doc.get("x", c[1] if c else 530)),
            "y": float(doc.get("y", c[2] if c else 350)),
            "active_cases": doc.get("active_cases", 0),
            "page_count_1hr": doc.get("page_count_1hr", 0),
        })

    assigned = None
    if best:
        fz = _doctor_floor_z(best)
        assigned = {**best, "floor_z": fz}

    return jsonify({
        "patient_zone": patient_zone,
        "patient_coords": patient_coords,
        "assigned_doctor": assigned,
        "path_zones": best_path,
        "path_coords": path_coords,
        "eta_minutes": round(best_cost, 2),
        "all_doctors": all_docs,
        "specialty_queried": specialty,
    })
