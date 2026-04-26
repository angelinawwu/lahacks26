"""
Page lifecycle + queue management routes.
Replaces backend/routes/pages.py and backend/routes/queue.py.

Pages are now persisted to TinyDB (db/pages.json) so they survive restarts.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import shared_state as state
from api.sio import sio

router = APIRouter()
_log = logging.getLogger("medpage.pages")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Operator page request (with EHR context + optional scheduling)
# ---------------------------------------------------------------------------

class PageRequestIn(BaseModel):
    raw_text: str = ""
    room: Optional[str] = None
    priority: Optional[str] = "P2"
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    chief_complaint: Optional[str] = None
    vitals: Optional[str] = None
    scheduled_for: Optional[str] = None   # ISO datetime string; None = immediate
    requested_by: Optional[str] = "operator"


def _ehr_for(patient_id: Optional[str]) -> dict:
    """Return the EHR record for a patient_id, or {} if not found."""
    if not patient_id:
        return {}
    return state.EHR.get(patient_id, {}) or {}


def _build_raw_text(req: PageRequestIn) -> str:
    """Assemble a rich natural-language situation string for the agent.

    Always prepends the operator-supplied free text (if any), then layers EHR
    context so the priority classifier and specialty matcher have everything
    they need. EHR fields are silently skipped when missing.
    """
    parts: list[str] = []

    # 1. Operator's free-text situation (highest signal for the classifier).
    if req.raw_text and req.raw_text.strip():
        parts.append(req.raw_text.strip())

    # 2. Operator-entered manual fields.
    if req.chief_complaint:
        parts.append(f"Chief complaint: {req.chief_complaint}")
    if req.patient_name:
        parts.append(f"Patient: {req.patient_name}")
    if req.patient_age:
        parts.append(f"Age: {req.patient_age}")
    if req.vitals:
        parts.append(f"Vitals: {req.vitals}")
    if req.room:
        parts.append(f"Location: {req.room}")

    # 3. EHR context (when patient_id resolves to a known record).
    ehr = _ehr_for(req.patient_id)
    if ehr:
        if ehr.get("primary_diagnosis"):
            parts.append(f"Diagnosis: {ehr['primary_diagnosis']}")
        if ehr.get("comorbidities"):
            parts.append(f"Comorbidities: {', '.join(ehr['comorbidities'])}")
        if ehr.get("allergies"):
            parts.append(f"Allergies: {', '.join(ehr['allergies'])}")
        if ehr.get("assigned_team"):
            parts.append(f"Care team: {', '.join(ehr['assigned_team'])}")
        if ehr.get("primary_physician"):
            parts.append(f"Primary: {ehr['primary_physician']}")

    return ". ".join(parts) if parts else "Operator page request"


def _specialty_hint_for(req: PageRequestIn) -> Optional[str]:
    """Pick a specialty hint from the EHR's assigned_team, if available.

    The first item in `assigned_team` is treated as the primary specialty,
    which steers the agent's specialty matcher directly. Returns None when no
    EHR record exists or the field is missing — the agent will fall back to
    parsing the free text.
    """
    ehr = _ehr_for(req.patient_id)
    team = ehr.get("assigned_team") if ehr else None
    if isinstance(team, list) and team:
        return team[0]
    if isinstance(team, str) and team.strip():
        return team.strip()
    return None


async def _fire_page_request(request_id: str) -> None:
    """Called immediately or after a scheduled delay — runs the dispatch pipeline."""
    req_data = state.SCHEDULED_PAGES.get(request_id)
    if not req_data:
        return
    req_data["status"] = "dispatching"
    state.SCHEDULED_PAGES[request_id] = req_data

    try:
        from api.main import process_alert, _emit_dispatch_from_decision, AlertMessage  # type: ignore[import]
    except Exception as e:
        _log.error("page-request: agent stack unavailable: %s", e)
        req_data["status"] = "failed"
        state.SCHEDULED_PAGES[request_id] = req_data
        return

    if process_alert is None:
        _log.error("page-request: process_alert not loaded")
        req_data["status"] = "failed"
        state.SCHEDULED_PAGES[request_id] = req_data
        return

    try:
        msg = AlertMessage(
            raw_text=req_data["raw_text"],
            room=req_data.get("room"),
            patient_id=req_data.get("patient_id"),
            specialty_hint=req_data.get("specialty_hint"),
            requested_by=req_data.get("requested_by", "operator"),
        )
        decision = await process_alert(msg)
        await _emit_dispatch_from_decision(msg, decision)
        req_data["status"] = "dispatched"
        state.SCHEDULED_PAGES[request_id] = req_data
        await sio.emit("page_dispatched", {"request_id": request_id, **req_data}, room="operators")
    except Exception as e:
        _log.error("page-request dispatch error: %s", e)
        req_data["status"] = "failed"
        state.SCHEDULED_PAGES[request_id] = req_data


async def _schedule_and_fire(request_id: str, delay_seconds: float) -> None:
    await asyncio.sleep(delay_seconds)
    await _fire_page_request(request_id)


@router.post("/api/page-request")
async def create_page_request(req: PageRequestIn):
    """
    Operator submits a page request with patient context.
    - Enriches raw_text from EHR / manual fields.
    - If scheduled_for is set, delays dispatch until that time.
    - Otherwise dispatches immediately via the AI pipeline.
    """
    request_id = uuid4().hex
    raw_text = _build_raw_text(req)
    specialty_hint = _specialty_hint_for(req)
    ehr_matched = bool(req.patient_id and req.patient_id in state.EHR)

    record: dict = {
        "request_id": request_id,
        "raw_text": raw_text,
        "room": req.room,
        "priority": req.priority,
        "patient_id": req.patient_id,
        "patient_name": req.patient_name,
        "specialty_hint": specialty_hint,
        "ehr_matched": ehr_matched,
        "requested_by": req.requested_by,
        "created_at": _now(),
        "scheduled_for": req.scheduled_for,
        "status": "pending",
    }
    state.SCHEDULED_PAGES[request_id] = record

    if req.scheduled_for:
        try:
            scheduled_dt = datetime.fromisoformat(req.scheduled_for.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            delay = max(0.0, (scheduled_dt - now_dt).total_seconds())
        except ValueError:
            delay = 0.0

        record["status"] = "scheduled"
        state.SCHEDULED_PAGES[request_id] = record
        await sio.emit("page_scheduled", record, room="operators")
        asyncio.create_task(_schedule_and_fire(request_id, delay))
        return record

    # Immediate dispatch
    asyncio.create_task(_fire_page_request(request_id))
    return record


# ---------------------------------------------------------------------------
# Page CRUD
# ---------------------------------------------------------------------------

@router.get("/api/pages")
def list_pages():
    return list(state.PAGES.values())


@router.get("/api/pages/{page_id}")
def get_page(page_id: str):
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    return page


@router.post("/api/page", status_code=201)
async def create_page(request: Request):
    """
    Trigger a page to a doctor. Called by the AI agent or operator.

    Required body: doctor_id
    Optional: patient_id, message, priority, room, requested_by, backup_doctors
    """
    body = await request.json()

    doctor_id = body.get("doctor_id")
    if not doctor_id:
        raise HTTPException(status_code=400, detail="doctor_id is required")

    patient_id = body.get("patient_id")
    message = body.get("message", "")
    priority = body.get("priority", "P2")
    room = body.get("room")
    requested_by = body.get("requested_by")
    backup_doctors = body.get("backup_doctors", [])

    page_id = uuid4().hex
    created_at = _now()

    page = {
        "id": page_id,
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "message": message,
        "priority": priority,
        "room": room,
        "requested_by": requested_by,
        "backup_doctors": backup_doctors,
        "status": "paging",
        "created_at": created_at,
        "responded_at": None,
        "outcome": None,
        "escalation_history": [],
    }

    # Persist to TinyDB + in-memory
    state.save_page(page)

    # Keep doctor stats current
    doc = state.DOCTORS.get(doctor_id)
    if doc:
        doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1
        if patient_id:
            doc["active_cases"] = doc.get("active_cases", 0) + 1

    await sio.emit("doctor_paged", page, room="operators")
    await sio.emit(
        "incoming_page",
        {
            "page_id": page_id,
            "message": message,
            "patient_id": patient_id,
            "room": room,
            "priority": priority,
            "created_at": created_at,
            "ack_deadline_seconds": 60,
        },
        room=doctor_id,
    )

    return page


@router.post("/api/page/{page_id}/respond")
async def respond_to_page(page_id: str, request: Request):
    """
    Record a doctor's response (accept / decline).

    On accept: spawns SBAR brief generation in the background.
    """
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")

    body = await request.json()
    outcome = body.get("outcome")
    if outcome not in ("accept", "decline"):
        raise HTTPException(status_code=400, detail="outcome must be 'accept' or 'decline'")

    page["outcome"] = outcome
    page["status"] = "accepted" if outcome == "accept" else "declined"
    page["responded_at"] = _now()
    state.save_page(page)

    await sio.emit("page_response", page, room="operators")

    if outcome == "accept":
        doc = state.DOCTORS.get(page.get("doctor_id"))
        if doc:
            doc["status"] = "on_case"
            await sio.emit(
                "doctor_status_changed", {"id": doc["id"], **doc}, room="operators"
            )
        # Non-blocking brief generation
        asyncio.create_task(_generate_and_deliver_brief(dict(page)))

    return page


@router.post("/api/page/{page_id}/resolve")
async def resolve_page(page_id: str):
    """Mark a page as resolved; flip doctor back to available."""
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")

    if page.get("status") == "resolved":
        return page

    page["status"] = "resolved"
    page["outcome"] = "resolved"
    page["resolved_at"] = _now()
    state.save_page(page)

    doc_id = page.get("doctor_id")
    doc = state.DOCTORS.get(doc_id) if doc_id else None
    if doc:
        doc["status"] = "available"
        doc["active_cases"] = max(0, int(doc.get("active_cases", 0)) - 1)
        await sio.emit(
            "doctor_status_changed", {"id": doc["id"], **doc}, room="operators"
        )

    await sio.emit("page_response", page, room="operators")
    if doc_id:
        await sio.emit(
            "page_resolved",
            {"page_id": page_id, "alert_id": page_id, "outcome": "resolved"},
            room=doc_id,
        )

    return page


# ---------------------------------------------------------------------------
# Background brief generation
# ---------------------------------------------------------------------------

async def _generate_and_deliver_brief(page: dict) -> None:
    """Generate an SBAR brief for the accepting clinician and emit it via socket."""
    try:
        from agents.skills.brief import generate_brief_sync  # type: ignore[import]
    except Exception as e:
        _log.warning("brief skill unavailable: %s", e)
        return

    page_id = page.get("id", "")
    clinician_id = page.get("doctor_id", "")
    patient_id = page.get("patient_id")

    patient = None
    if patient_id:
        p = state.PATIENTS.get(patient_id)
        if p:
            ehr = state.EHR.get(patient_id, {})
            patient = {**p, **(ehr or {})}

    alert = {
        "raw_text": page.get("message", ""),
        "priority": page.get("priority"),
        "room": page.get("room"),
    }
    scene = {
        "requested_by": page.get("requested_by"),
        "paged_at": page.get("created_at"),
        "responded_at": page.get("responded_at"),
        "escalated_from": (
            (page.get("escalation_history") or [{}])[-1].get("from_doctor")
            if page.get("escalation_history")
            else None
        ),
    }

    try:
        brief = await asyncio.to_thread(
            generate_brief_sync,
            alert=alert,
            patient=patient,
            scene=scene,
            page_id=page_id,
            clinician_id=clinician_id,
        )
    except Exception as e:
        _log.warning("brief generation failed: %s", e)
        return

    payload = {
        "page_id": brief.page_id,
        "clinician_id": brief.clinician_id,
        "patient_id": brief.patient_id,
        "brief_text": brief.brief_text,
        "word_count": brief.word_count,
        "generated_at": brief.generated_at,
        "created_at": brief.generated_at,   # alias for frontend SbarBrief.created_at
    }

    # Store in-memory so GET /api/brief/<page_id> works
    state.BRIEFS[page_id] = payload

    await sio.emit("sbar_brief", payload, room=clinician_id)
    await sio.emit("sbar_brief", payload, room="operators")


# ---------------------------------------------------------------------------
# Queue management (was backend/routes/queue.py)
# ---------------------------------------------------------------------------

@router.post("/api/page/{page_id}/approve")
async def approve_page(page_id: str, request: Request):
    """
    Operator approves a pending_approval page.

    Optional body: { override_doctor_id: string }
    If override_doctor_id is provided, the page is reassigned to that doctor
    before being sent out.
    """
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    if page.get("status") != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"page is not pending approval (status={page.get('status')})",
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    override_doctor_id = body.get("override_doctor_id")
    if override_doctor_id:
        old_doctor_id = page.get("doctor_id")
        page["doctor_id"] = override_doctor_id
        if old_doctor_id != override_doctor_id:
            page.setdefault("escalation_history", []).append({
                "from_doctor": old_doctor_id,
                "to_doctor": override_doctor_id,
                "timestamp": _now(),
                "reason": "operator_override",
            })
        # Update doctor stat
        doc = state.DOCTORS.get(override_doctor_id)
        if doc:
            doc["page_count_1hr"] = doc.get("page_count_1hr", 0) + 1

    doctor_id = page["doctor_id"]
    page["status"] = "paging"
    page["approved_at"] = _now()
    state.save_page(page)

    await sio.emit("alert_created", page, room="operators")
    if doctor_id:
        await sio.emit(
            "incoming_page",
            {
                "page_id": page_id,
                "alert_id": page_id,
                "title": page.get("title") or page.get("message") or page_id,
                "message": page.get("message", ""),
                "patient_id": page.get("patient_id"),
                "room": page.get("room"),
                "priority": page.get("priority"),
                "reasoning": page.get("reasoning", ""),
                "created_at": page.get("created_at"),
                "ack_deadline_seconds": page.get("ack_deadline_seconds", 60),
            },
            room=doctor_id,
        )

    return page


@router.post("/api/page/{page_id}/reject")
async def reject_page(page_id: str):
    """Operator rejects a pending_approval page — no page is sent to any doctor."""
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    if page.get("status") != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"page is not pending approval (status={page.get('status')})",
        )

    page["status"] = "rejected"
    page["rejected_at"] = _now()
    state.save_page(page)

    await sio.emit("page_cancelled", page, room="operators")
    return page


@router.get("/api/queue")
def get_queue():
    """Active page queue sorted by priority then creation time."""
    active_pages = [
        p for p in state.PAGES.values()
        if p["status"] in ("paging", "pending", "escalated")
    ]

    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    active_pages.sort(
        key=lambda p: (priority_order.get(p.get("priority", "P4"), 4), p.get("created_at", ""))
    )

    enhanced = []
    for page in active_pages:
        ep = dict(page)
        doc_id = page.get("doctor_id")
        if doc_id and doc_id in state.DOCTORS:
            d = state.DOCTORS[doc_id]
            ep["doctor"] = {
                "name": d.get("name"),
                "specialty": d.get("specialty"),
                "zone": d.get("zone"),
                "status": d.get("status"),
            }
        created = page.get("created_at")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                elapsed = (datetime.now() - created_dt.replace(tzinfo=None)).total_seconds()
                timeouts = {"P1": 30, "P2": 60, "P3": 120, "P4": 300}
                timeout = timeouts.get(page.get("priority", "P4"), 60)
                ep["time_remaining_seconds"] = int(max(0, timeout - elapsed))
                ep["timeout_seconds"] = timeout
                ep["elapsed_seconds"] = int(elapsed)
            except Exception:
                ep["time_remaining_seconds"] = 0
                ep["timeout_seconds"] = 60
        if "escalation_history" in page:
            ep["escalation_count"] = len(page["escalation_history"])
        enhanced.append(ep)

    return {
        "pages": enhanced,
        "total": len(enhanced),
        "by_priority": {
            p: len([x for x in active_pages if x.get("priority") == p])
            for p in ("P1", "P2", "P3", "P4")
        },
    }


@router.get("/api/queue/stats")
def get_queue_stats():
    pages = list(state.PAGES.values())
    active = [p for p in pages if p["status"] in ("paging", "pending", "escalated")]
    completed = [p for p in pages if p["status"] in ("accepted", "declined")]

    response_times: list = []
    for p in completed:
        created = p.get("created_at")
        responded = p.get("responded_at")
        if created and responded:
            try:
                c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                r_dt = datetime.fromisoformat(responded.replace("Z", "+00:00"))
                response_times.append((p["priority"], (r_dt - c_dt).total_seconds()))
            except Exception:
                pass

    avg_response = {}
    for prio in ("P1", "P2", "P3", "P4"):
        times = [t for pr, t in response_times if pr == prio]
        if times:
            avg_response[prio] = sum(times) / len(times)

    return {
        "active_pages": len(active),
        "total_pages_today": len(pages),
        "by_priority": {p: len([x for x in active if x.get("priority") == p]) for p in ("P1", "P2", "P3", "P4")},
        "by_status": {
            s: len([p for p in pages if p.get("status") == s])
            for s in ("pending", "escalated", "accepted", "declined", "expired", "cancelled")
        },
        "average_response_times": avg_response,
        "escalation_count": len([p for p in pages if p.get("escalation_history")]),
    }


@router.get("/api/queue/{page_id}")
def get_queue_page(page_id: str):
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    return page


@router.get("/api/queue/doctors/{doctor_id}/pending")
def get_doctor_pending_pages(doctor_id: str):
    if doctor_id not in state.DOCTORS:
        raise HTTPException(status_code=404, detail=f"doctor {doctor_id} not found")
    return [
        p for p in state.PAGES.values()
        if p.get("doctor_id") == doctor_id
        and p.get("status") in ("paging", "pending", "escalated")
    ]


@router.post("/api/queue/{page_id}/escalate")
async def manual_escalate(page_id: str, request: Request):
    """Operator manually escalates a page to the next backup doctor."""
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    if page.get("status") not in ("paging", "pending"):
        raise HTTPException(status_code=400, detail=f"page cannot be escalated (status={page.get('status')})")

    backup_doctors = list(page.get("backup_doctors", []))
    current_doctor_id = page.get("doctor_id")

    next_doctor_id: Optional[str] = None
    for i, bid in enumerate(backup_doctors):
        if bid != current_doctor_id:
            next_doctor_id = bid
            backup_doctors.pop(i)
            break

    if not next_doctor_id:
        raise HTTPException(status_code=400, detail="no backup doctors available")

    old_doctor = page["doctor_id"]
    page["doctor_id"] = next_doctor_id
    page["backup_doctors"] = backup_doctors
    page["status"] = "escalated"
    page["escalated_at"] = _now()
    page.setdefault("escalation_history", []).append({
        "from_doctor": old_doctor,
        "to_doctor": next_doctor_id,
        "timestamp": _now(),
        "reason": "manual_escalation",
    })
    state.save_page(page)

    await sio.emit("page_escalated", page, room="operators")
    await sio.emit(
        "incoming_page",
        {
            "page_id": page_id,
            "message": f"[ESCALATED] {page.get('message', '')}",
            "patient_id": page.get("patient_id"),
            "room": page.get("room"),
            "priority": page.get("priority"),
            "created_at": page.get("created_at"),
            "escalated_from": old_doctor,
            "ack_deadline_seconds": 60,
        },
        room=next_doctor_id,
    )

    return page


@router.post("/api/queue/{page_id}/cancel")
async def cancel_page(page_id: str):
    """Operator cancels a pending page."""
    page = state.PAGES.get(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"page {page_id} not found")
    if page.get("status") in ("accepted", "declined", "expired"):
        raise HTTPException(status_code=400, detail=f"page already completed (status={page.get('status')})")

    page["status"] = "cancelled"
    page["cancelled_at"] = _now()
    state.save_page(page)

    await sio.emit("page_cancelled", page, room="operators")
    return page
