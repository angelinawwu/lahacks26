"""
Paging modes — manual vs automated, per zone, with operator override and
direct manual pinging.

Modes:
  "automated"  — system selects and pages the best clinician automatically
  "manual"     — operator must confirm or choose the clinician before any
                 page is sent; alert stays in "pending_review" status

Mode resolution order (most specific wins):
  1. Per-page override  (set on a specific alert/page)
  2. Per-zone policy    (zone-level default)
  3. Global default     (hospital-wide)

Operator override endpoints let operators:
  - Switch global or zone mode instantly
  - Force a single page to be sent manually or automated regardless of policy
  - Manually ping a specific clinician directly (bypasses auto-dispatch)
  - Cancel an override (revert to zone/global policy)

State lives in state.PAGING_MODES dict — cleared on restart.

Endpoints:
  GET  /api/paging-modes                          — global + all zone modes
  PUT  /api/paging-modes/global                   — set global default mode
  GET  /api/paging-modes/zone/<zone_id>           — get zone policy
  PUT  /api/paging-modes/zone/<zone_id>           — set zone policy
  DELETE /api/paging-modes/zone/<zone_id>         — remove zone override (reverts to global)
  GET  /api/paging-modes/page/<page_id>           — get per-page override
  POST /api/paging-modes/override                 — set per-page mode override
  DELETE /api/paging-modes/override/<page_id>     — remove per-page override
  POST /api/paging-modes/manual-ping              — operator manually pings a clinician
  GET  /api/paging-modes/resolve/<zone_id>        — resolve effective mode for a zone
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from flask import Blueprint, jsonify, request, current_app
import state

bp = Blueprint("paging_modes", __name__)
_log = logging.getLogger("medpage.paging_modes")

VALID_MODES = ("automated", "manual")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Shared state accessor
# ---------------------------------------------------------------------------

def _get_modes() -> Dict[str, Any]:
    """
    Return (and lazily initialise) the PAGING_MODES state dict.

    Structure:
    {
      "global_mode": "automated",
      "global_set_by": None,
      "global_set_at": None,
      "zones": {
          "icu": {"mode": "manual", "set_by": "op_1", "set_at": "..."},
          ...
      },
      "page_overrides": {
          "<page_id>": {"mode": "manual", "set_by": "op_1", "set_at": "..."},
          ...
      },
    }
    """
    if not hasattr(state, "PAGING_MODES"):
        state.PAGING_MODES = {  # type: ignore[attr-defined]
            "global_mode": "automated",
            "global_set_by": None,
            "global_set_at": None,
            "zones": {},
            "page_overrides": {},
        }
    return state.PAGING_MODES  # type: ignore[attr-defined]


def resolve_mode(zone_id: Optional[str] = None, page_id: Optional[str] = None) -> str:
    """
    Return the effective paging mode given optional zone and page context.
    Most-specific wins: page_override > zone > global.
    """
    modes = _get_modes()

    if page_id and page_id in modes.get("page_overrides", {}):
        return modes["page_overrides"][page_id]["mode"]

    if zone_id and zone_id in modes.get("zones", {}):
        return modes["zones"][zone_id]["mode"]

    return modes.get("global_mode", "automated")


def _emit_modes_update() -> None:
    try:
        from flask import current_app as ca
        ca.socketio.emit("paging_modes_updated", _get_modes(), room="operators")
    except Exception as exc:
        _log.warning("paging_modes emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Routes — global
# ---------------------------------------------------------------------------

@bp.get("/api/paging-modes")
def get_paging_modes():
    """Return global mode + all zone and page overrides."""
    return jsonify(_get_modes())


@bp.put("/api/paging-modes/global")
def set_global_mode():
    """
    Set the hospital-wide default paging mode.

    Body (JSON):
      { "mode": "automated" | "manual", "operator_id": "op_1", "reason": "..." }
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    if mode not in VALID_MODES:
        return jsonify({"error": f"mode must be one of {VALID_MODES}"}), 400

    modes = _get_modes()
    old_mode = modes["global_mode"]
    modes["global_mode"] = mode
    modes["global_set_by"] = body.get("operator_id")
    modes["global_set_at"] = _now()
    modes["global_reason"] = body.get("reason", "")

    _emit_modes_update()
    _log.info("Global paging mode: %s → %s (by %s)", old_mode, mode, body.get("operator_id"))
    return jsonify({
        "status": "updated",
        "global_mode": mode,
        "previous_mode": old_mode,
        "set_by": modes["global_set_by"],
        "set_at": modes["global_set_at"],
    })


# ---------------------------------------------------------------------------
# Routes — per-zone
# ---------------------------------------------------------------------------

@bp.get("/api/paging-modes/zone/<zone_id>")
def get_zone_mode(zone_id: str):
    """Return the paging mode for a specific zone."""
    modes = _get_modes()
    zone_entry = modes["zones"].get(zone_id)
    effective = resolve_mode(zone_id=zone_id)
    return jsonify({
        "zone": zone_id,
        "zone_override": zone_entry,
        "global_mode": modes["global_mode"],
        "effective_mode": effective,
    })


@bp.put("/api/paging-modes/zone/<zone_id>")
def set_zone_mode(zone_id: str):
    """
    Set the paging mode for a specific zone.

    Body (JSON):
      { "mode": "automated" | "manual", "operator_id": "op_1", "reason": "..." }
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    if mode not in VALID_MODES:
        return jsonify({"error": f"mode must be one of {VALID_MODES}"}), 400

    modes = _get_modes()
    old_entry = modes["zones"].get(zone_id)
    entry = {
        "mode": mode,
        "set_by": body.get("operator_id"),
        "set_at": _now(),
        "reason": body.get("reason", ""),
    }
    modes["zones"][zone_id] = entry

    _emit_modes_update()
    _log.info("Zone %s mode → %s (by %s)", zone_id, mode, body.get("operator_id"))
    return jsonify({
        "zone": zone_id,
        "mode": mode,
        "previous": old_entry,
        "entry": entry,
        "effective_mode": resolve_mode(zone_id=zone_id),
    })


@bp.delete("/api/paging-modes/zone/<zone_id>")
def clear_zone_mode(zone_id: str):
    """Remove zone-level override (zone reverts to global default)."""
    modes = _get_modes()
    removed = modes["zones"].pop(zone_id, None)
    if removed is None:
        return jsonify({"status": "no_override", "zone": zone_id})
    _emit_modes_update()
    return jsonify({
        "status": "cleared",
        "zone": zone_id,
        "removed": removed,
        "effective_mode": modes["global_mode"],
    })


# ---------------------------------------------------------------------------
# Routes — per-page overrides
# ---------------------------------------------------------------------------

@bp.get("/api/paging-modes/page/<page_id>")
def get_page_override(page_id: str):
    """Return the paging mode override (if any) for a specific page."""
    modes = _get_modes()
    override = modes["page_overrides"].get(page_id)
    page = state.PAGES.get(page_id)
    zone_id = page.get("room") if page else None
    effective = resolve_mode(zone_id=zone_id, page_id=page_id)
    return jsonify({
        "page_id": page_id,
        "override": override,
        "effective_mode": effective,
    })


@bp.post("/api/paging-modes/override")
def set_page_override():
    """
    Override the paging mode for a single in-flight page.
    Operator can force a page that was pending review to go automated,
    or hold an automated page for manual confirmation.

    Body (JSON):
      page_id     : str  (required)
      mode        : "automated" | "manual"  (required)
      operator_id : str
      reason      : str
    """
    body = request.get_json(silent=True) or {}
    page_id = body.get("page_id")
    mode = body.get("mode")

    if not page_id:
        return jsonify({"error": "page_id is required"}), 400
    if mode not in VALID_MODES:
        return jsonify({"error": f"mode must be one of {VALID_MODES}"}), 400

    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "page_id": page_id}), 404

    modes = _get_modes()
    entry = {
        "mode": mode,
        "set_by": body.get("operator_id"),
        "set_at": _now(),
        "reason": body.get("reason", ""),
    }
    modes["page_overrides"][page_id] = entry

    # Reflect mode on the page record itself for visibility
    page["paging_mode_override"] = mode
    page["paging_mode_set_by"] = body.get("operator_id")

    _emit_modes_update()
    try:
        current_app.socketio.emit("alert_updated", page, room="operators")
    except Exception:
        pass

    _log.info("Page %s mode overridden → %s (by %s)", page_id, mode, body.get("operator_id"))
    return jsonify({
        "page_id": page_id,
        "override": entry,
        "page_status": page.get("status"),
    })


@bp.delete("/api/paging-modes/override/<page_id>")
def clear_page_override(page_id: str):
    """Remove the per-page mode override (page reverts to zone/global policy)."""
    modes = _get_modes()
    removed = modes["page_overrides"].pop(page_id, None)
    page = state.PAGES.get(page_id)
    zone_id = page.get("room") if page else None
    effective = resolve_mode(zone_id=zone_id)
    if removed is None:
        return jsonify({"status": "no_override", "page_id": page_id, "effective_mode": effective})
    _emit_modes_update()
    return jsonify({
        "status": "cleared",
        "page_id": page_id,
        "removed": removed,
        "effective_mode": effective,
    })


# ---------------------------------------------------------------------------
# Resolve effective mode for a zone (utility)
# ---------------------------------------------------------------------------

@bp.get("/api/paging-modes/resolve/<zone_id>")
def resolve_zone_mode(zone_id: str):
    """
    Return the effective paging mode for a zone with full audit trail.
    Useful for the operator dashboard to display why a particular mode is active.
    """
    modes = _get_modes()
    zone_entry = modes["zones"].get(zone_id)
    effective = resolve_mode(zone_id=zone_id)
    source = "zone_override" if zone_entry else "global"

    return jsonify({
        "zone": zone_id,
        "effective_mode": effective,
        "source": source,
        "zone_entry": zone_entry,
        "global_mode": modes["global_mode"],
        "global_set_by": modes.get("global_set_by"),
        "global_set_at": modes.get("global_set_at"),
    })


# ---------------------------------------------------------------------------
# Manual ping — operator directly pages a specific clinician
# ---------------------------------------------------------------------------

@bp.post("/api/paging-modes/manual-ping")
def manual_ping():
    """
    Operator manually pings a specific clinician, bypassing auto-dispatch.
    Can be used even when zone mode is "automated" — this is a one-off direct page.

    Body (JSON):
      doctor_id   : str   (required)
      message     : str   (required — operator's custom message)
      priority    : "P1" | "P2" | "P3" | "P4"   (default "P2")
      room        : str   (optional)
      patient_id  : str   (optional)
      operator_id : str   (optional)
      urgent      : bool  (default false — if true, ack_deadline is 30s)

    Side effects:
      - Creates a page record in state.PAGES with source="manual_operator"
      - Emits `doctor_paged`  → operators room
      - Emits `incoming_page` → individual doctor room (with "OPERATOR PING" flag)
      - Emits `paging_modes_updated` if this overrides an existing auto-dispatch
    """
    body = request.get_json(silent=True) or {}
    doctor_id = body.get("doctor_id")
    message = (body.get("message") or "").strip()

    if not doctor_id:
        return jsonify({"error": "doctor_id is required"}), 400
    if not message:
        return jsonify({"error": "message is required"}), 400
    if doctor_id not in state.DOCTORS:
        return jsonify({"error": "doctor not found", "doctor_id": doctor_id}), 404

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
        "id": page_id,
        "source": "manual_operator",
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "message": message,
        "priority": priority,
        "room": room,
        "requested_by": operator_id,
        "backup_doctors": [],
        "status": "paging",
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
        "escalation_history": [],
        "paging_mode": "manual",
        "operator_ping": True,
        "urgent": urgent,
    }
    state.PAGES[page_id] = page

    doc = state.DOCTORS.get(doctor_id, {})
    doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
    if patient_id:
        doc["active_cases"] = doc.get("active_cases", 0) + 1

    sio = current_app.socketio
    sio.emit("doctor_paged", page, room="operators")
    sio.emit(
        "incoming_page",
        {
            "page_id": page_id,
            "message": f"[OPERATOR PING] {message}",
            "patient_id": patient_id,
            "room": room,
            "priority": priority,
            "created_at": created_at,
            "ack_deadline_seconds": ack_deadline,
            "source": "manual_operator",
            "urgent": urgent,
        },
        room=doctor_id,
    )

    _log.info(
        "Manual ping %s → %s (priority=%s urgent=%s) by %s",
        page_id, doctor_id, priority, urgent, operator_id,
    )
    return jsonify(page), 201


# ---------------------------------------------------------------------------
# Bulk zone-mode listing
# ---------------------------------------------------------------------------

@bp.get("/api/paging-modes/zones")
def list_zone_modes():
    """
    Return the effective paging mode for every known zone (from state.ROOMS).
    Includes zones with explicit overrides and zones using the global default.
    """
    modes = _get_modes()
    result: List[Dict[str, Any]] = []
    seen_zones = set()

    # Zones with explicit overrides
    for zone_id, entry in modes["zones"].items():
        result.append({
            "zone": zone_id,
            "effective_mode": entry["mode"],
            "source": "zone_override",
            "entry": entry,
        })
        seen_zones.add(zone_id)

    # Remaining zones from room data
    for room_id in state.ROOMS:
        if room_id not in seen_zones:
            result.append({
                "zone": room_id,
                "effective_mode": modes["global_mode"],
                "source": "global",
                "entry": None,
            })

    return jsonify({
        "global_mode": modes["global_mode"],
        "zones": result,
        "total": len(result),
    })
