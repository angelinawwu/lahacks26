"""
Settings, paging modes, and clinician priority queue routes.
Replaces backend/routes/settings.py, paging_modes.py, clinician_queue.py.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from api import shared_state as state
from api.sio import sio

router = APIRouter()
_log = logging.getLogger("medpage.settings")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_REPO_ROOT, "config", "autonomy_config.json")

VALID_MODES = ("automated", "manual")
VALID_VIEWS = ("map", "feed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# Settings
# ===========================================================================

def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def _flatten_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    rules = cfg.get("auto_dispatch_rules", {}) or {}
    paging_modes = state.PAGING_MODES or {}
    return {
        "max_pages_per_hour": rules.get("max_pages_per_hour", 3),
        "require_on_call": rules.get("require_on_call", True),
        "allow_off_shift": rules.get("allow_off_shift", False),
        "default_operator_view": cfg.get("default_operator_view", "map"),
        "global_mode": paging_modes.get("global_mode", "automated"),
    }


@router.get("/api/settings")
def get_settings():
    return _flatten_settings(_load_config())


@router.put("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    cfg = _load_config()
    rules = cfg.setdefault("auto_dispatch_rules", {})

    if "max_pages_per_hour" in body:
        try:
            rules["max_pages_per_hour"] = max(1, int(body["max_pages_per_hour"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_pages_per_hour must be an integer")

    if "require_on_call" in body:
        rules["require_on_call"] = bool(body["require_on_call"])
    if "allow_off_shift" in body:
        rules["allow_off_shift"] = bool(body["allow_off_shift"])
    if "default_operator_view" in body:
        view = body["default_operator_view"]
        if view not in VALID_VIEWS:
            raise HTTPException(status_code=400, detail=f"default_operator_view must be one of {VALID_VIEWS}")
        cfg["default_operator_view"] = view

    _save_config(cfg)
    flat = _flatten_settings(cfg)
    await sio.emit("settings_updated", flat, room="operators")
    return flat


# ===========================================================================
# Paging Modes
# ===========================================================================

def _get_modes() -> Dict[str, Any]:
    return state.PAGING_MODES


def resolve_mode(zone_id: Optional[str] = None, page_id: Optional[str] = None) -> str:
    modes = _get_modes()
    if page_id and page_id in modes.get("page_overrides", {}):
        return modes["page_overrides"][page_id]["mode"]
    if zone_id and zone_id in modes.get("zones", {}):
        return modes["zones"][zone_id]["mode"]
    return modes.get("global_mode", "automated")


async def _emit_modes_update() -> None:
    try:
        await sio.emit("paging_modes_updated", _get_modes(), room="operators")
    except Exception as exc:
        _log.warning("paging_modes emit failed: %s", exc)


@router.get("/api/paging-modes")
def get_paging_modes():
    return _get_modes()


@router.put("/api/paging-modes/global")
async def set_global_mode(request: Request):
    body = await request.json()
    mode = body.get("mode")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")
    modes = _get_modes()
    old_mode = modes["global_mode"]
    modes["global_mode"] = mode
    modes["global_set_by"] = body.get("operator_id")
    modes["global_set_at"] = _now()
    modes["global_reason"] = body.get("reason", "")
    await _emit_modes_update()
    return {"status": "updated", "global_mode": mode, "previous_mode": old_mode,
            "set_by": modes["global_set_by"], "set_at": modes["global_set_at"]}


@router.get("/api/paging-modes/zones")
def list_zone_modes():
    modes = _get_modes()
    result: List[Dict[str, Any]] = []
    seen_zones = set()
    for zone_id, entry in modes["zones"].items():
        result.append({"zone": zone_id, "effective_mode": entry["mode"],
                        "source": "zone_override", "entry": entry})
        seen_zones.add(zone_id)
    for room_id in state.ROOMS:
        if room_id not in seen_zones:
            result.append({"zone": room_id, "effective_mode": modes["global_mode"],
                            "source": "global", "entry": None})
    return {"global_mode": modes["global_mode"], "zones": result, "total": len(result)}


@router.get("/api/paging-modes/resolve/{zone_id}")
def resolve_zone_mode(zone_id: str):
    modes = _get_modes()
    zone_entry = modes["zones"].get(zone_id)
    effective = resolve_mode(zone_id=zone_id)
    return {
        "zone": zone_id, "effective_mode": effective,
        "source": "zone_override" if zone_entry else "global",
        "zone_entry": zone_entry, "global_mode": modes["global_mode"],
        "global_set_by": modes.get("global_set_by"), "global_set_at": modes.get("global_set_at"),
    }


@router.get("/api/paging-modes/zone/{zone_id}")
def get_zone_mode(zone_id: str):
    modes = _get_modes()
    return {
        "zone": zone_id,
        "zone_override": modes["zones"].get(zone_id),
        "global_mode": modes["global_mode"],
        "effective_mode": resolve_mode(zone_id=zone_id),
    }


@router.put("/api/paging-modes/zone/{zone_id}")
async def set_zone_mode(zone_id: str, request: Request):
    body = await request.json()
    mode = body.get("mode")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")
    modes = _get_modes()
    entry = {"mode": mode, "set_by": body.get("operator_id"), "set_at": _now(), "reason": body.get("reason", "")}
    old = modes["zones"].get(zone_id)
    modes["zones"][zone_id] = entry
    await _emit_modes_update()
    return {"zone": zone_id, "mode": mode, "previous": old, "entry": entry,
            "effective_mode": resolve_mode(zone_id=zone_id)}


@router.delete("/api/paging-modes/zone/{zone_id}")
async def clear_zone_mode(zone_id: str):
    modes = _get_modes()
    removed = modes["zones"].pop(zone_id, None)
    if removed is None:
        return {"status": "no_override", "zone": zone_id}
    await _emit_modes_update()
    return {"status": "cleared", "zone": zone_id, "removed": removed,
            "effective_mode": modes["global_mode"]}


@router.get("/api/paging-modes/page/{page_id}")
def get_page_override(page_id: str):
    modes = _get_modes()
    page = state.PAGES.get(page_id)
    zone_id = page.get("room") if page else None
    return {
        "page_id": page_id,
        "override": modes["page_overrides"].get(page_id),
        "effective_mode": resolve_mode(zone_id=zone_id, page_id=page_id),
    }


@router.post("/api/paging-modes/override")
async def set_page_override(request: Request):
    body = await request.json()
    page_id = body.get("page_id")
    mode = body.get("mode")
    if not page_id:
        raise HTTPException(status_code=400, detail="page_id is required")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {VALID_MODES}")
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    modes = _get_modes()
    entry = {"mode": mode, "set_by": body.get("operator_id"), "set_at": _now(), "reason": body.get("reason", "")}
    modes["page_overrides"][page_id] = entry
    page["paging_mode_override"] = mode
    page["paging_mode_set_by"] = body.get("operator_id")
    state.save_page(page)
    await _emit_modes_update()
    await sio.emit("alert_updated", page, room="operators")
    return {"page_id": page_id, "override": entry, "page_status": page.get("status")}


@router.delete("/api/paging-modes/override/{page_id}")
async def clear_page_override(page_id: str):
    modes = _get_modes()
    removed = modes["page_overrides"].pop(page_id, None)
    page = state.PAGES.get(page_id)
    zone_id = page.get("room") if page else None
    effective = resolve_mode(zone_id=zone_id)
    if removed is None:
        return {"status": "no_override", "page_id": page_id, "effective_mode": effective}
    await _emit_modes_update()
    return {"status": "cleared", "page_id": page_id, "removed": removed, "effective_mode": effective}


@router.post("/api/paging-modes/manual-ping", status_code=201)
async def manual_ping(request: Request):
    """Operator manually pings a clinician, bypassing auto-dispatch."""
    body = await request.json()
    doctor_id = body.get("doctor_id")
    message = (body.get("message") or "").strip()
    if not doctor_id:
        raise HTTPException(status_code=400, detail="doctor_id is required")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if doctor_id not in state.DOCTORS:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")

    priority = body.get("priority", "P2")
    if priority not in ("P1", "P2", "P3", "P4"):
        priority = "P2"
    urgent = bool(body.get("urgent", False))
    ack_deadline = 30 if urgent or priority == "P1" else 60
    room = body.get("room")
    patient_id = body.get("patient_id")
    operator_id = body.get("operator_id")

    page_id = uuid4().hex
    created_at = _now()
    page = {
        "id": page_id, "source": "manual_operator", "doctor_id": doctor_id,
        "patient_id": patient_id, "message": message, "priority": priority,
        "room": room, "requested_by": operator_id, "backup_doctors": [],
        "status": "paging", "created_at": created_at, "responded_at": None,
        "outcome": None, "escalation_history": [], "paging_mode": "manual",
        "operator_ping": True, "urgent": urgent,
    }
    state.save_page(page)

    doc = state.DOCTORS.get(doctor_id, {})
    doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
    if patient_id:
        doc["active_cases"] = doc.get("active_cases", 0) + 1

    await sio.emit("doctor_paged", page, room="operators")
    await sio.emit(
        "incoming_page",
        {
            "page_id": page_id, "message": f"[OPERATOR PING] {message}",
            "patient_id": patient_id, "room": room, "priority": priority,
            "created_at": created_at, "ack_deadline_seconds": ack_deadline,
            "source": "manual_operator", "urgent": urgent,
        },
        room=doctor_id,
    )
    return page


# ===========================================================================
# Clinician Priority Queue
# ===========================================================================

def _get_queue() -> Dict[str, Dict[str, Any]]:
    return state.CLINICIAN_QUEUE


def _auto_score(doc: Dict[str, Any]) -> float:
    score = 0.0
    if doc.get("status") == "available":
        score += 20
    elif doc.get("status") == "on_break":
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
    queue = _get_queue()
    pinned: List[Dict[str, Any]] = []
    ranked: List[Dict[str, Any]] = []
    auto: List[Dict[str, Any]] = []

    for doctor_id, doc in state.DOCTORS.items():
        if specialty:
            spec_list = doc.get("specialty", [])
            spec_override = queue.get(doctor_id, {}).get("specialty_override", [])
            if specialty not in spec_list and specialty not in spec_override:
                continue
        q_entry = queue.get(doctor_id, {})
        merged = {
            **doc, "queue_entry": q_entry,
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


async def _emit_queue_update() -> None:
    try:
        await sio.emit("clinician_queue_updated", {"queue": _build_ordered_list()}, room="operators")
    except Exception as exc:
        _log.warning("clinician_queue emit failed: %s", exc)


@router.get("/api/clinician-queue")
def get_clinician_queue(specialty: Optional[str] = None, zone: Optional[str] = None):
    ordered = _build_ordered_list(specialty=specialty, zone=zone)
    return {"queue": ordered, "total": len(ordered), "filters": {"specialty": specialty, "zone": zone}}


@router.put("/api/clinician-queue")
async def replace_clinician_queue(request: Request):
    body = await request.json()
    order: List[str] = body.get("order", [])
    operator_id = body.get("operator_id")
    if not order:
        raise HTTPException(status_code=400, detail="'order' list is required")
    unknown = [did for did in order if did not in state.DOCTORS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown doctor IDs: {unknown}")
    queue = _get_queue()
    now = _now()
    for rank, doctor_id in enumerate(order, start=1):
        entry = queue.setdefault(doctor_id, {})
        entry.update({"doctor_id": doctor_id, "priority_rank": rank, "set_by": operator_id, "set_at": now})
    await _emit_queue_update()
    return {"status": "updated", "order": order, "updated_at": now}


@router.get("/api/clinician-queue/specialty/{specialty}")
def get_specialty_queue(specialty: str):
    ordered = _build_ordered_list(specialty=specialty)
    if not ordered:
        raise HTTPException(status_code=404, detail=f"no clinicians found for specialty {specialty}")
    available = [d for d in ordered if d.get("status") in ("available", "on_break")]
    busy = [d for d in ordered if d.get("status") not in ("available", "on_break", "off_shift")]
    off_shift = [d for d in ordered if d.get("status") == "off_shift"]
    return {
        "specialty": specialty, "dispatch_order": ordered,
        "available": available, "busy": busy, "off_shift": off_shift,
        "top_candidate": available[0] if available else None,
    }


@router.get("/api/clinician-queue/{doctor_id}")
def get_clinician_queue_entry(doctor_id: str):
    if doctor_id not in state.DOCTORS:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    return {**state.DOCTORS[doctor_id], "queue_entry": _get_queue().get(doctor_id, {})}


@router.put("/api/clinician-queue/{doctor_id}")
async def upsert_clinician_queue_entry(doctor_id: str, request: Request):
    if doctor_id not in state.DOCTORS:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    body = await request.json()
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
    await _emit_queue_update()
    return {**state.DOCTORS[doctor_id], "queue_entry": entry}


@router.delete("/api/clinician-queue/{doctor_id}")
async def remove_clinician_queue_entry(doctor_id: str):
    removed = _get_queue().pop(doctor_id, None)
    if removed is None:
        return {"status": "no_entry", "doctor_id": doctor_id}
    await _emit_queue_update()
    return {"status": "removed", "doctor_id": doctor_id, "removed_entry": removed}


@router.post("/api/clinician-queue/{doctor_id}/pin")
async def pin_clinician(doctor_id: str, request: Request):
    if doctor_id not in state.DOCTORS:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    body = await request.json()
    queue = _get_queue()
    entry = queue.setdefault(doctor_id, {})
    entry.update({
        "doctor_id": doctor_id, "pinned": True,
        "priority_rank": int(body.get("rank", 1)),
        "set_by": body.get("operator_id"), "set_at": _now(),
    })
    if "notes" in body:
        entry["notes"] = body["notes"]
    await _emit_queue_update()
    return {**state.DOCTORS[doctor_id], "queue_entry": entry}


@router.delete("/api/clinician-queue/{doctor_id}/pin")
async def unpin_clinician(doctor_id: str):
    entry = _get_queue().get(doctor_id)
    if not entry:
        return {"status": "not_pinned", "doctor_id": doctor_id}
    entry["pinned"] = False
    entry["set_at"] = _now()
    await _emit_queue_update()
    return {"status": "unpinned", "doctor_id": doctor_id, "entry": entry}
