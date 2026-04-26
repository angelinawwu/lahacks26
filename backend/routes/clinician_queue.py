"""
Clinician priority queue — operator-editable dispatch ordering.

The priority queue determines which clinician is selected first when
the system auto-dispatches a page to a specialty.  Operators can:
  - Reorder the queue via drag-and-drop (PUT /api/clinician-queue)
  - Set an explicit priority rank for one clinician
  - Pin a clinician to the top of all specialty queues
  - Unpin / remove overrides

Queue entries layer on top of the base doctor data.  Each entry stores:
  doctor_id, priority_rank (lower = higher priority), pinned, notes,
  specialty_override (if this clinician should handle a non-primary specialty),
  set_by (operator_id), set_at.

The computed dispatch order for a specialty is:
  1. Pinned clinicians in the specialty (rank order)
  2. Non-pinned clinicians with explicit ranks (rank order)
  3. Remaining available clinicians by auto-score (status, page_count, zone)

Endpoints:
  GET  /api/clinician-queue                    — full queue with computed order
  PUT  /api/clinician-queue                    — replace entire ordering
  GET  /api/clinician-queue/<doctor_id>        — single clinician queue entry
  PUT  /api/clinician-queue/<doctor_id>        — upsert queue entry
  DELETE /api/clinician-queue/<doctor_id>      — remove queue override
  POST /api/clinician-queue/<doctor_id>/pin    — pin to top
  DELETE /api/clinician-queue/<doctor_id>/pin  — unpin
  GET  /api/clinician-queue/specialty/<spec>   — ordered list for a specialty
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("clinician_queue", __name__)
_log = logging.getLogger("medpage.clinician_queue")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Access the shared queue from state
# ---------------------------------------------------------------------------

def _get_queue() -> Dict[str, Dict[str, Any]]:
    """Return the in-memory clinician queue dict from state."""
    if not hasattr(state, "CLINICIAN_QUEUE"):
        state.CLINICIAN_QUEUE = {}  # type: ignore[attr-defined]
    return state.CLINICIAN_QUEUE  # type: ignore[attr-defined]


def _auto_score(doc: Dict[str, Any]) -> float:
    """
    Score a doctor for auto-dispatch when no explicit rank exists.
    Higher score = dispatched sooner.
    """
    score = 0.0
    status = doc.get("status", "")
    if status == "available":
        score += 20
    elif status == "on_break":
        score += 5
    if doc.get("on_call"):
        score += 10
    score -= doc.get("page_count_1hr", 0) * 2
    score -= doc.get("active_cases", 0)
    return score


def _build_ordered_list(
    specialty: Optional[str] = None,
    zone: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return a combined list of clinician dicts merged with their queue entries,
    ordered by: pinned first → explicit rank → auto-score.
    """
    queue = _get_queue()
    pinned: List[Dict[str, Any]] = []
    ranked: List[Dict[str, Any]] = []
    auto: List[Dict[str, Any]] = []

    for doctor_id, doc in state.DOCTORS.items():
        # Specialty filter
        if specialty:
            spec_list = doc.get("specialty", [])
            q_entry = queue.get(doctor_id, {})
            spec_override = q_entry.get("specialty_override", [])
            if specialty not in spec_list and specialty not in spec_override:
                continue

        # Zone filter (soft)
        if zone and doc.get("zone") and zone not in doc.get("zone", ""):
            pass  # still include, just lower priority handled by auto-score

        q_entry = queue.get(doctor_id, {})
        merged = {
            **doc,
            "queue_entry": q_entry,
            "pinned": q_entry.get("pinned", False),
            "priority_rank": q_entry.get("priority_rank"),
            "notes": q_entry.get("notes"),
            "set_by": q_entry.get("set_by"),
            "set_at": q_entry.get("set_at"),
        }

        if q_entry.get("pinned"):
            pinned.append(merged)
        elif q_entry.get("priority_rank") is not None:
            ranked.append(merged)
        else:
            auto.append(merged)

    pinned.sort(key=lambda d: d.get("priority_rank") or 999)
    ranked.sort(key=lambda d: d.get("priority_rank") or 999)
    auto.sort(key=lambda d: _auto_score(d), reverse=True)

    return pinned + ranked + auto


def _emit_queue_update() -> None:
    """Push the updated full queue to the operators room."""
    try:
        from flask import current_app as ca
        ca.socketio.emit(
            "clinician_queue_updated",
            {"queue": _build_ordered_list()},
            room="operators",
        )
    except Exception as exc:
        _log.warning("queue emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/api/clinician-queue")
def get_queue():
    """Return the full operator-visible priority queue."""
    specialty = request.args.get("specialty")
    zone = request.args.get("zone")
    ordered = _build_ordered_list(specialty=specialty, zone=zone)
    return jsonify({
        "queue": ordered,
        "total": len(ordered),
        "filters": {"specialty": specialty, "zone": zone},
    })


@bp.put("/api/clinician-queue")
def replace_queue():
    """
    Replace the entire ordering.  Useful when the operator drags and drops
    the list in the UI and sends the new full order.

    Body (JSON):
      { "order": ["dr_chen", "dr_rodriguez", ...], "operator_id": "op_1" }

    Each doctor ID gets a priority_rank equal to its index + 1.
    Any existing pins are preserved (they stay pinned at their new rank).
    """
    body = request.get_json(silent=True) or {}
    order: List[str] = body.get("order", [])
    operator_id = body.get("operator_id")
    if not order:
        return jsonify({"error": "'order' list is required"}), 400

    unknown = [did for did in order if did not in state.DOCTORS]
    if unknown:
        return jsonify({"error": "unknown doctor IDs", "ids": unknown}), 400

    queue = _get_queue()
    now = _now()
    for rank, doctor_id in enumerate(order, start=1):
        entry = queue.setdefault(doctor_id, {})
        entry["doctor_id"] = doctor_id
        entry["priority_rank"] = rank
        entry["set_by"] = operator_id
        entry["set_at"] = now

    _emit_queue_update()
    _log.info("Queue reordered by %s — %d entries", operator_id, len(order))
    return jsonify({"status": "updated", "order": order, "updated_at": now})


@bp.get("/api/clinician-queue/<doctor_id>")
def get_queue_entry(doctor_id: str):
    """Return the queue entry + live doctor data for one clinician."""
    if doctor_id not in state.DOCTORS:
        return jsonify({"error": "doctor not found", "id": doctor_id}), 404
    queue = _get_queue()
    doc = state.DOCTORS[doctor_id]
    entry = queue.get(doctor_id, {})
    return jsonify({**doc, "queue_entry": entry})


@bp.put("/api/clinician-queue/<doctor_id>")
def upsert_queue_entry(doctor_id: str):
    """
    Upsert a queue entry for one clinician.

    Body (JSON, all optional):
      priority_rank     : int — lower = higher priority
      pinned            : bool
      notes             : str — operator notes (e.g. "primary trauma tonight")
      specialty_override: list[str] — add extra specialties for dispatch
      operator_id       : str
    """
    if doctor_id not in state.DOCTORS:
        return jsonify({"error": "doctor not found", "id": doctor_id}), 404

    body = request.get_json(silent=True) or {}
    queue = _get_queue()
    entry = queue.setdefault(doctor_id, {})
    entry["doctor_id"] = doctor_id

    if "priority_rank" in body:
        entry["priority_rank"] = int(body["priority_rank"])
    if "pinned" in body:
        entry["pinned"] = bool(body["pinned"])
    if "notes" in body:
        entry["notes"] = str(body["notes"])
    if "specialty_override" in body:
        entry["specialty_override"] = list(body["specialty_override"])

    entry["set_by"] = body.get("operator_id")
    entry["set_at"] = _now()

    queue[doctor_id] = entry
    _emit_queue_update()

    return jsonify({**state.DOCTORS[doctor_id], "queue_entry": entry})


@bp.delete("/api/clinician-queue/<doctor_id>")
def remove_queue_entry(doctor_id: str):
    """Remove all queue overrides for a clinician (revert to auto-ordering)."""
    queue = _get_queue()
    removed = queue.pop(doctor_id, None)
    if removed is None:
        return jsonify({"status": "no_entry", "doctor_id": doctor_id})
    _emit_queue_update()
    return jsonify({"status": "removed", "doctor_id": doctor_id, "removed_entry": removed})


@bp.post("/api/clinician-queue/<doctor_id>/pin")
def pin_clinician(doctor_id: str):
    """
    Pin a clinician to the top of the dispatch queue.

    Body (JSON, all optional):
      rank        : int — rank among pinned (default 1)
      notes       : str
      operator_id : str
    """
    if doctor_id not in state.DOCTORS:
        return jsonify({"error": "doctor not found", "id": doctor_id}), 404

    body = request.get_json(silent=True) or {}
    queue = _get_queue()
    entry = queue.setdefault(doctor_id, {})
    entry["doctor_id"] = doctor_id
    entry["pinned"] = True
    entry["priority_rank"] = int(body.get("rank", 1))
    if "notes" in body:
        entry["notes"] = body["notes"]
    entry["set_by"] = body.get("operator_id")
    entry["set_at"] = _now()

    _emit_queue_update()
    doc = state.DOCTORS[doctor_id]
    _log.info("Clinician %s pinned (rank=%d) by %s", doctor_id, entry["priority_rank"], entry["set_by"])
    return jsonify({**doc, "queue_entry": entry})


@bp.delete("/api/clinician-queue/<doctor_id>/pin")
def unpin_clinician(doctor_id: str):
    """Unpin a clinician (they stay in the queue at their explicit rank if set)."""
    queue = _get_queue()
    entry = queue.get(doctor_id)
    if not entry:
        return jsonify({"status": "not_pinned", "doctor_id": doctor_id})
    entry["pinned"] = False
    entry["set_at"] = _now()
    _emit_queue_update()
    return jsonify({"status": "unpinned", "doctor_id": doctor_id, "entry": entry})


@bp.get("/api/clinician-queue/specialty/<specialty>")
def get_specialty_queue(specialty: str):
    """
    Return the ordered dispatch list for a specific specialty.
    Includes available, on-break, and in-procedure clinicians, ranked in order.
    """
    ordered = _build_ordered_list(specialty=specialty)
    if not ordered:
        return jsonify({"error": "no clinicians found for specialty", "specialty": specialty}), 404

    available = [d for d in ordered if d.get("status") in ("available", "on_break")]
    busy = [d for d in ordered if d.get("status") not in ("available", "on_break", "off_shift")]
    off_shift = [d for d in ordered if d.get("status") == "off_shift"]

    return jsonify({
        "specialty": specialty,
        "dispatch_order": ordered,
        "available": available,
        "busy": busy,
        "off_shift": off_shift,
        "top_candidate": available[0] if available else None,
    })
