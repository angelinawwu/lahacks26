"""
Proactive recommendations + SBAR brief delivery routes.
Replaces backend/routes/proactive.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from api import shared_state as state
from api.sio import sio

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Proactive recommendations
# ---------------------------------------------------------------------------

@router.post("/api/proactive/recommendation", status_code=201)
async def push_recommendation(request: Request):
    """Operator Agent pushes a recommendation derived from a SentinelInsight."""
    body = await request.json()
    insight_id = body.get("insight_id")
    if not insight_id:
        raise HTTPException(status_code=400, detail="insight_id is required")

    created_at = body.get("created_at", _now())
    rec = {
        "id": insight_id,           # frontend uses rec.id for dedup/ACK
        "insight_id": insight_id,
        "pattern_type": body.get("pattern_type", "unknown"),
        "severity": body.get("severity", "warning"),
        "recommendation": body.get("recommendation", ""),
        "rationale": body.get("rationale", ""),
        "suggested_actions": body.get("suggested_actions", []),
        "requires_ack": bool(body.get("requires_ack", True)),
        "status": "pending",
        "created_at": created_at,
        "acked_at": None,
        "acked_by": None,
        "ack_outcome": None,
        "zone": body.get("zone"),
        "specialty": body.get("specialty"),
    }
    state.RECOMMENDATIONS[insight_id] = rec
    await sio.emit("proactive_recommendation", rec, room="operators")

    # Derive a PatternSignal so CoverageBanner updates immediately.
    pattern_signal = {
        "id": insight_id,
        "pattern_type": rec["pattern_type"],
        "severity": rec["severity"],
        "zone": rec.get("zone"),
        "specialty": rec.get("specialty"),
        "rooms": body.get("rooms", []),
        "message": rec["recommendation"],
        "created_at": created_at,
    }
    await sio.emit("pattern_detected", pattern_signal, room="operators")
    return rec


@router.get("/api/proactive")
def list_recommendations():
    items = sorted(
        state.RECOMMENDATIONS.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )
    return {
        "pending": [r for r in items if r.get("status") == "pending"],
        "all": items,
    }


@router.get("/api/proactive/{insight_id}")
def get_recommendation(insight_id: str):
    rec = state.RECOMMENDATIONS.get(insight_id)
    if not rec:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return rec


@router.post("/api/proactive/{insight_id}/ack")
async def ack_recommendation(insight_id: str, request: Request):
    """Operator ACKs (approves or rejects) a recommendation."""
    rec = state.RECOMMENDATIONS.get(insight_id)
    if not rec:
        raise HTTPException(status_code=404, detail="recommendation not found")

    body = await request.json()
    outcome = body.get("outcome")
    if outcome not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="outcome must be 'approve' or 'reject'")

    rec["status"] = "acked"
    rec["ack_outcome"] = outcome
    rec["acked_at"] = _now()
    rec["acked_by"] = body.get("operator_id")

    await sio.emit("proactive_recommendation_acked", rec, room="operators")

    # Clear the corresponding pattern from CoverageBanner.
    await sio.emit(
        "pattern_cleared",
        {
            "id": insight_id,
            "pattern_type": rec.get("pattern_type"),
            "zone": rec.get("zone"),
            "specialty": rec.get("specialty"),
        },
        room="operators",
    )
    return rec


# ---------------------------------------------------------------------------
# SBAR brief delivery (pushed by Operator Agent or backend background task)
# ---------------------------------------------------------------------------

@router.post("/api/brief/deliver", status_code=201)
async def deliver_brief(request: Request):
    """Operator Agent calls this after generating a brief; we emit it to the clinician."""
    body = await request.json()
    page_id = body.get("page_id")
    clinician_id = body.get("clinician_id")
    brief_text = body.get("brief_text")
    if not page_id or not clinician_id or not brief_text:
        raise HTTPException(status_code=400, detail="page_id, clinician_id, brief_text are required")

    generated_at = body.get("generated_at", _now())
    brief = {
        "page_id": page_id,
        "clinician_id": clinician_id,
        "patient_id": body.get("patient_id"),
        "brief_text": brief_text,
        "word_count": int(body.get("word_count") or len(str(brief_text).split())),
        "generated_at": generated_at,
        "created_at": generated_at,   # alias for frontend SbarBrief.created_at
    }
    state.BRIEFS[page_id] = brief

    await sio.emit("sbar_brief", brief, room=clinician_id)
    await sio.emit("sbar_brief", brief, room="operators")
    return brief


@router.get("/api/brief/{page_id}")
def get_brief(page_id: str):
    brief = state.BRIEFS.get(page_id)
    if not brief:
        raise HTTPException(status_code=404, detail="brief not found")
    return brief
