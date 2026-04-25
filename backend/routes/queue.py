"""
Queue management API routes for MedPage backend.

Provides endpoints for:
- Viewing the page queue
- Manual escalation
- Cancelling pages
- Getting queue statistics
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app
from datetime import datetime

import state

bp = Blueprint("queue", __name__)


@bp.get("/api/queue")
def get_queue():
    """
    Get the full page queue with all pending/escalated pages.
    Returns pages sorted by priority (P1 first) then creation time.
    """
    # Build queue from active pages with queue tracking
    active_pages = [
        p for p in state.PAGES.values()
        if p["status"] in ("paging", "pending", "escalated")
    ]
    
    # Sort by priority (P1 < P2 < P3 < P4) then by created_at
    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    active_pages.sort(key=lambda p: (
        priority_order.get(p.get("priority", "P4"), 4),
        p.get("created_at", "")
    ))
    
    # Enhance with doctor info
    enhanced = []
    for page in active_pages:
        enhanced_page = dict(page)
        
        # Add doctor info
        doctor_id = page.get("doctor_id")
        if doctor_id and doctor_id in state.DOCTORS:
            doc = state.DOCTORS[doctor_id]
            enhanced_page["doctor"] = {
                "name": doc.get("name"),
                "specialty": doc.get("specialty"),
                "zone": doc.get("zone"),
                "status": doc.get("status")
            }
        
        # Calculate time remaining
        created = page.get("created_at")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                elapsed = (datetime.now() - created_dt.replace(tzinfo=None)).total_seconds()
                
                # Timeout based on priority
                timeouts = {"P1": 30, "P2": 60, "P3": 120, "P4": 300}
                timeout = timeouts.get(page.get("priority", "P4"), 60)
                remaining = max(0, timeout - elapsed)
                
                enhanced_page["time_remaining_seconds"] = int(remaining)
                enhanced_page["timeout_seconds"] = timeout
                enhanced_page["elapsed_seconds"] = int(elapsed)
            except:
                enhanced_page["time_remaining_seconds"] = 0
                enhanced_page["timeout_seconds"] = 60
        
        # Add escalation info if present
        if "escalation_history" in page:
            enhanced_page["escalation_count"] = len(page["escalation_history"])
        
        enhanced.append(enhanced_page)
    
    return jsonify({
        "pages": enhanced,
        "total": len(enhanced),
        "by_priority": {
            "P1": len([p for p in active_pages if p.get("priority") == "P1"]),
            "P2": len([p for p in active_pages if p.get("priority") == "P2"]),
            "P3": len([p for p in active_pages if p.get("priority") == "P3"]),
            "P4": len([p for p in active_pages if p.get("priority") == "P4"]),
        }
    })


@bp.get("/api/queue/<page_id>")
def get_queue_page(page_id):
    """Get details of a specific page in the queue."""
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404
    
    return jsonify(page)


@bp.post("/api/queue/<page_id>/escalate")
def manual_escalate(page_id):
    """
    Manually escalate a page to the next doctor.
    Operator can use this to skip the current doctor.
    """
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404
    
    if page.get("status") not in ("paging", "pending"):
        return jsonify({"error": "page cannot be escalated", "status": page.get("status")}), 400
    
    # Get next doctor from backup list
    current_doctor_id = page.get("doctor_id")
    backup_doctors = page.get("backup_doctors", [])
    
    if not backup_doctors:
        return jsonify({"error": "no backup doctors available"}), 400
    
    # Find next doctor (skip current)
    next_doctor_id = None
    for i, backup_id in enumerate(backup_doctors):
        if backup_id != current_doctor_id:
            next_doctor_id = backup_id
            # Remove from backup list
            backup_doctors.pop(i)
            break
    
    if not next_doctor_id:
        return jsonify({"error": "no more backup doctors"}), 400
    
    # Update page
    old_doctor = page["doctor_id"]
    page["doctor_id"] = next_doctor_id
    page["backup_doctors"] = backup_doctors
    page["status"] = "escalated"
    page["escalated_at"] = datetime.now().isoformat()
    
    # Track escalation history
    if "escalation_history" not in page:
        page["escalation_history"] = []
    page["escalation_history"].append({
        "from_doctor": old_doctor,
        "to_doctor": next_doctor_id,
        "timestamp": datetime.now().isoformat(),
        "reason": "manual_escalation"
    })
    
    # Emit events
    sio = current_app.socketio
    
    # Notify operators
    sio.emit("page_escalated", page, room="operators")
    
    # Notify new doctor
    doc = state.DOCTORS.get(next_doctor_id)
    if doc:
        sio.emit("incoming_page", {
            "page_id": page_id,
            "message": f"[ESCALATED] {page.get('message', '')}",
            "patient_id": page.get("patient_id"),
            "room": page.get("room"),
            "priority": page.get("priority"),
            "created_at": page.get("created_at"),
            "escalated_from": old_doctor,
            "ack_deadline_seconds": 60,
        }, room=next_doctor_id)
    
    return jsonify(page)


@bp.post("/api/queue/<page_id>/cancel")
def cancel_page(page_id):
    """Cancel a pending page (operator intervention)."""
    page = state.PAGES.get(page_id)
    if not page:
        return jsonify({"error": "page not found", "id": page_id}), 404
    
    if page.get("status") in ("accepted", "declined", "expired"):
        return jsonify({"error": "page already completed", "status": page.get("status")}), 400
    
    page["status"] = "cancelled"
    page["cancelled_at"] = datetime.now().isoformat()
    
    # Emit event
    sio = current_app.socketio
    sio.emit("page_cancelled", page, room="operators")
    
    return jsonify(page)


@bp.get("/api/queue/stats")
def get_queue_stats():
    """Get queue statistics for dashboard."""
    pages = list(state.PAGES.values())
    
    active = [p for p in pages if p["status"] in ("paging", "pending", "escalated")]
    
    # Average response times by priority
    completed = [p for p in pages if p["status"] in ("accepted", "declined")]
    response_times = []
    for p in completed:
        created = p.get("created_at")
        responded = p.get("responded_at")
        if created and responded:
            try:
                created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                responded_dt = datetime.fromisoformat(responded.replace('Z', '+00:00'))
                response_times.append((p["priority"], (responded_dt - created_dt).total_seconds()))
            except:
                pass
    
    avg_response = {}
    for prio in ["P1", "P2", "P3", "P4"]:
        times = [t for p, t in response_times if p == prio]
        if times:
            avg_response[prio] = sum(times) / len(times)
    
    return jsonify({
        "active_pages": len(active),
        "total_pages_today": len(pages),
        "by_priority": {
            "P1": len([p for p in active if p.get("priority") == "P1"]),
            "P2": len([p for p in active if p.get("priority") == "P2"]),
            "P3": len([p for p in active if p.get("priority") == "P3"]),
            "P4": len([p for p in active if p.get("priority") == "P4"]),
        },
        "by_status": {
            "pending": len([p for p in pages if p.get("status") == "pending"]),
            "escalated": len([p for p in pages if p.get("status") == "escalated"]),
            "accepted": len([p for p in pages if p.get("status") == "accepted"]),
            "declined": len([p for p in pages if p.get("status") == "declined"]),
            "expired": len([p for p in pages if p.get("status") == "expired"]),
            "cancelled": len([p for p in pages if p.get("status") == "cancelled"]),
        },
        "average_response_times": avg_response,
        "escalation_count": len([p for p in pages if "escalation_history" in p])
    })


@bp.get("/api/queue/doctors/<doctor_id>/pending")
def get_doctor_pending_pages(doctor_id):
    """Get all pending pages for a specific doctor."""
    if doctor_id not in state.DOCTORS:
        return jsonify({"error": "doctor not found"}), 404
    
    pending = [
        p for p in state.PAGES.values()
        if p.get("doctor_id") == doctor_id
        and p.get("status") in ("paging", "pending", "escalated")
    ]
    
    return jsonify(pending)
