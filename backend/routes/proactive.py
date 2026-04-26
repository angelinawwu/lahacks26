"""
Proactive recommendations + SBAR brief delivery routes.

Glue between the agent network and the operator/clinician dashboards:
  - POST /api/proactive/recommendation  ← Operator Agent pushes when Sentinel
                                            insight produces a recommendation.
                                            Emits `proactive_recommendation`
                                            socket event to operators.
  - POST /api/proactive/<id>/ack         ← Operator dashboard ACKs (or rejects)
                                            a recommendation. Required before
                                            any action is taken.
  - GET  /api/proactive                  ← Pending recommendations list.
  - POST /api/brief/deliver              ← Operator Agent pushes a generated
                                            SBAR brief; we forward it to the
                                            clinician via Socket.IO.
  - GET  /api/brief/<page_id>            ← Fetch the latest brief for a page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any

from flask import Blueprint, jsonify, request, current_app

import state

bp = Blueprint("proactive", __name__)


# In-memory stores. Survive only as long as the backend process — fine for
# the demo and the Sentinel re-emits patterns that still apply.
RECOMMENDATIONS: Dict[str, Dict[str, Any]] = {}
BRIEFS: Dict[str, Dict[str, Any]] = {}  # keyed by page_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Proactive recommendations
# ---------------------------------------------------------------------------
@bp.post("/api/proactive/recommendation")
def push_recommendation():
    """
    Called by the Operator Agent when it has a proactive recommendation
    derived from a SentinelInsight. The operator dashboard subscribes to
    the `proactive_recommendation` socket event.
    """
    body = request.get_json(silent=True) or {}
    insight_id = body.get("insight_id")
    if not insight_id:
        return jsonify({"error": "insight_id is required"}), 400

    rec = {
        "insight_id": insight_id,
        "pattern_type": body.get("pattern_type", "unknown"),
        "severity": body.get("severity", "warning"),
        "recommendation": body.get("recommendation", ""),
        "rationale": body.get("rationale", ""),
        "suggested_actions": body.get("suggested_actions", []),
        "requires_ack": bool(body.get("requires_ack", True)),
        "status": "pending",
        "created_at": body.get("created_at", _now()),
        "acked_at": None,
        "acked_by": None,
        "ack_outcome": None,
    }
    RECOMMENDATIONS[insight_id] = rec

    sio = current_app.socketio
    sio.emit("proactive_recommendation", rec, room="operators")
    return jsonify(rec), 201


@bp.get("/api/proactive")
def list_recommendations():
    """List pending + recent recommendations, newest first."""
    items = sorted(
        RECOMMENDATIONS.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )
    return jsonify({
        "pending": [r for r in items if r.get("status") == "pending"],
        "all": items,
    })


@bp.get("/api/proactive/<insight_id>")
def get_recommendation(insight_id: str):
    rec = RECOMMENDATIONS.get(insight_id)
    if not rec:
        return jsonify({"error": "recommendation not found"}), 404
    return jsonify(rec)


@bp.post("/api/proactive/<insight_id>/ack")
def ack_recommendation(insight_id: str):
    """
    Operator ACKs (approves or rejects) a recommendation.
    Body: { "outcome": "approve" | "reject", "operator_id": "op_1" }
    Only after `approve` should any suggested action be enacted by the agent.
    """
    rec = RECOMMENDATIONS.get(insight_id)
    if not rec:
        return jsonify({"error": "recommendation not found"}), 404

    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("approve", "reject"):
        return jsonify({"error": "outcome must be 'approve' or 'reject'"}), 400

    rec["status"] = "acked"
    rec["ack_outcome"] = outcome
    rec["acked_at"] = _now()
    rec["acked_by"] = body.get("operator_id")

    sio = current_app.socketio
    sio.emit("proactive_recommendation_acked", rec, room="operators")
    return jsonify(rec)


# ---------------------------------------------------------------------------
# SBAR brief delivery
# ---------------------------------------------------------------------------
@bp.post("/api/brief/deliver")
def deliver_brief():
    """
    Called by the Operator Agent right after `generate_brief` runs (which
    happens the moment a clinician accepts a page). We store the brief and
    forward it to the clinician via Socket.IO.
    """
    body = request.get_json(silent=True) or {}
    page_id = body.get("page_id")
    clinician_id = body.get("clinician_id")
    brief_text = body.get("brief_text")
    if not page_id or not clinician_id or not brief_text:
        return jsonify({
            "error": "page_id, clinician_id, brief_text are required"
        }), 400

    brief = {
        "page_id": page_id,
        "clinician_id": clinician_id,
        "patient_id": body.get("patient_id"),
        "brief_text": brief_text,
        "word_count": int(body.get("word_count") or len(str(brief_text).split())),
        "generated_at": body.get("generated_at", _now()),
    }
    BRIEFS[page_id] = brief

    sio = current_app.socketio
    # Send to the clinician's personal socket room
    sio.emit("sbar_brief", brief, room=clinician_id)
    # Mirror to operators dashboard for visibility
    sio.emit("sbar_brief", brief, room="operators")
    return jsonify(brief), 201


@bp.get("/api/brief/<page_id>")
def get_brief(page_id: str):
    brief = BRIEFS.get(page_id)
    if not brief:
        return jsonify({"error": "brief not found"}), 404
    return jsonify(brief)
