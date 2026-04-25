"""
Operator Agent — the orchestrator (SYNCHRONOUS MODE).

Receives natural language alerts via Chat Protocol from ASI:One, coordinates
Priority Handler and Case Handler via direct function calls, synthesizes dispatch
decisions immediately. This synchronous approach is simpler and more reliable
for hackathon demos than async message passing.

Implements Chat Protocol from uagents_core.contrib.protocols.chat for ASI:One.
"""
from __future__ import annotations
import json
import os
import re
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from uagents import Agent, Context, Model
from uagents_core.contrib.protocols.chat import ChatMessage, ChatAcknowledgement

from agents.models import (
    AlertMessage as OurAlertMessage,
    PriorityResponse,
    CaseResponse,
    DispatchDecision,
)
from agents.asi_client import asi1_chat, extract_json
from agents.priority_handler import classify as priority_classify
from agents.case_handler import (
    query_clinicians,
    score_candidates,
    build_specialty_query,
    get_zone_from_room,
    rank_with_asi1,
    fallback_rank,
)
from agents.backend_client import get_backend_client, BackendClient
from agents.queue_manager import get_queue_manager, PageQueueManager
from tinydb import TinyDB
from datetime import datetime, timedelta
from typing import Tuple
import asyncio

load_dotenv()

# ============================================================================
# Autonomy Configuration Loading
# ============================================================================
AUTONOMY_CONFIG_PATH = os.getenv("AUTONOMY_CONFIG", "config/autonomy_config.json")

def load_autonomy_config() -> Dict[str, Any]:
    """Load autonomy configuration from JSON."""
    try:
        with open(AUTONOMY_CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        # Default to review mode if config missing
        return {
            "global_mode": "review",
            "zone_policies": {},
            "priority_policies": {
                "P1": {"mode": "review", "reason": "Emergency always reviewed"},
                "P2": {"mode": "autonomous", "reason": "Urgent ok for auto"},
                "P3": {"mode": "autonomous", "reason": "Important"},
                "P4": {"mode": "autonomous", "reason": "Routine"}
            }
        }

# ============================================================================
# EHR Matching
# ============================================================================
EHR_DB_PATH = os.getenv("EHR_DB", "db/ehr_records.json")

def lookup_ehr_by_room(room: str) -> Optional[Dict[str, Any]]:
    """Find patient EHR by room number."""
    if not room:
        return None
    try:
        db = TinyDB(EHR_DB_PATH)
        # Try exact room match
        results = db.search(lambda x: x.get("room", "").lower() == room.lower().replace("room", "").replace(" ", "").strip())
        return results[0] if results else None
    except Exception:
        return None

# ============================================================================
# Time-Queued Availability Prediction
# ============================================================================
SCHEDULE_DB_PATH = os.getenv("SCHEDULE_DB", "db/clinician_schedules.json")

def load_clinician_schedules() -> Dict[str, Dict[str, Any]]:
    """Load clinician availability schedules."""
    try:
        db = TinyDB(SCHEDULE_DB_PATH)
        return {doc["clinician_id"]: doc for doc in db.all()}
    except Exception:
        return {}

def get_clinician_availability(clinician_id: str, schedules: Dict) -> Tuple[str, Optional[datetime]]:
    """Get current status and estimated next availability."""
    sched = schedules.get(clinician_id, {})
    status = sched.get("status", "unknown")
    
    if status == "available":
        return "available", datetime.now()
    
    # Parse next available time
    eta_str = sched.get("next_available_eta")
    if eta_str:
        try:
            eta = datetime.fromisoformat(eta_str.replace('Z', '+00:00'))
            return status, eta
        except:
            pass
    
    # If in procedure, estimate from end time
    proc_end = sched.get("procedure_end_time")
    if proc_end:
        try:
            eta = datetime.fromisoformat(proc_end.replace('Z', '+00:00'))
            return status, eta
        except:
            pass
    
    return status, None

def find_future_available_clinicians(
    candidates: List[Dict],
    schedules: Dict[str, Dict],
    max_wait_minutes: int = 30
) -> List[Tuple[Dict, datetime]]:
    """Find clinicians who will be available within max_wait_minutes."""
    future_available = []
    now = datetime.now()
    cutoff = now + timedelta(minutes=max_wait_minutes)
    
    for cand in candidates:
        cid = cand["id"]
        status, eta = get_clinician_availability(cid, schedules)
        
        if status == "available":
            future_available.append((cand, now))
        elif eta and eta <= cutoff:
            future_available.append((cand, eta))
    
    # Sort by availability time
    future_available.sort(key=lambda x: x[1])
    return future_available

SEED = os.getenv("OPERATOR_SEED", "operator-dev-seed")
PORT = int(os.getenv("OPERATOR_PORT", "8001"))
DB_PATH = os.getenv("CLINICIANS_DB", "db/clinicians.json")

agent = Agent(
    name="operator_agent",
    seed=SEED,
    port=PORT,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)

# Zone travel map for tool use in dispatch reasoning
ZONE_TRAVEL_MINUTES = {
    ("floor_3_corridor", "icu"): 1,
    ("nurses_station", "icu"): 2,
    ("or_1", "icu"): 5,
    ("or_2", "icu"): 5,
    ("break_room", "icu"): 4,
    ("floor_3_corridor", "nurses_station"): 2,
    ("or_1", "nurses_station"): 6,
    ("or_2", "nurses_station"): 6,
    ("break_room", "nurses_station"): 3,
    ("floor_3_corridor", "or_1"): 4,
    ("icu", "or_1"): 5,
    ("nurses_station", "or_1"): 6,
    ("or_2", "or_1"): 2,
    ("break_room", "or_1"): 5,
    ("floor_3_corridor", "or_2"): 4,
    ("icu", "or_2"): 5,
    ("nurses_station", "or_2"): 6,
    ("break_room", "or_2"): 5,
}

SYSTEM_PROMPT_SYNTHESIZE = """You are the Operator in a hospital paging system.

You have received:
- An alert: {alert_text}
- Priority: {priority}
- Top candidate: {candidate_name} ({candidate_id})
- Candidate score: {score}
- Candidate reasoning: {candidate_reasoning}
- ETA: {eta} minutes

Write a ONE SENTENCE dispatch decision for the operator dashboard.
Be concise but include the key reasoning."""


def detect_mode(raw_text: str) -> str:
    """Detect sparse (<10 words) vs rich mode."""
    words = raw_text.split()
    if len(words) < 10:
        return "sparse"
    if len(words) < 15 and "room" not in raw_text.lower():
        return "sparse"
    return "rich"


def extract_room(text: str) -> Optional[str]:
    """Best-effort room extraction."""
    patterns = [
        r"room\s+(\d+)",
        r"rm\s+(\d+)",
        r"r(\d{3,4})",
        r"\b(\d{3,4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_specialty_hint(text: str) -> Optional[str]:
    """Best-effort specialty extraction from keywords."""
    low = text.lower()
    hints = {
        "cardiac": "cardiology", "cardiology": "cardiology", "heart": "cardiology",
        "chest pain": "cardiology", "stroke": "neurology", "neuro": "neurology",
        "brain": "neurology", "seizure": "neurology", "trauma": "trauma",
        "bleeding": "trauma", "surgery": "surgery", "or": "surgery",
    }
    for keyword, specialty in hints.items():
        if keyword in low:
            return specialty
    return None


def determine_autonomy_mode(
    autonomy_config: Dict[str, Any],
    priority: str,
    target_zone: str,
    ehr_data: Optional[Dict]
) -> Tuple[str, Optional[str]]:
    """
    Determine whether to use REVIEW or AUTONOMOUS mode.
    Returns: (mode, reason_if_zone_policy_applied)
    """
    global_mode = autonomy_config.get("global_mode", "review")
    
    # Priority-based policy check
    priority_policies = autonomy_config.get("priority_policies", {})
    if priority in priority_policies:
        prio_policy = priority_policies[priority]
        if prio_policy["mode"] == "review":
            return "review", f"Priority {priority}: {prio_policy.get('reason', 'policy')}"
    
    # Zone-based policy check
    zone_policies = autonomy_config.get("zone_policies", {})
    if target_zone in zone_policies:
        zone_policy = zone_policies[target_zone]
        if zone_policy["mode"] == "review":
            return "review", f"Zone {target_zone}: {zone_policy.get('reason', 'policy')}"
        # Zone explicitly allows autonomous
        return "autonomous", None
    
    # EHR-based override: if patient has primary physician on assigned team
    if ehr_data and ehr_data.get("assigned_team"):
        # Will check if assigned physician is available later
        pass  # Don't force review here, just use as tiebreaker
    
    return global_mode, None


# ============================================================================
# Enhanced Operator Guardrails
# ============================================================================

# Track recent pages per doctor for consecutive paging protection
_recent_pages: Dict[str, List[datetime]] = {}

def record_page_attempt(doctor_id: str):
    """Record a page attempt for consecutive paging protection."""
    now = datetime.now()
    if doctor_id not in _recent_pages:
        _recent_pages[doctor_id] = []
    _recent_pages[doctor_id].append(now)
    # Clean old entries (> 1 hour)
    _recent_pages[doctor_id] = [
        t for t in _recent_pages[doctor_id] 
        if (now - t).total_seconds() < 3600
    ]

def get_recent_page_count(doctor_id: str, minutes: int = 10) -> int:
    """Get number of pages to this doctor in last N minutes."""
    now = datetime.now()
    if doctor_id not in _recent_pages:
        return 0
    cutoff = now - timedelta(minutes=minutes)
    return len([t for t in _recent_pages[doctor_id] if t > cutoff])

def apply_workload_guardrails(
    candidates: List[Dict],
    priority: str,
    guardrail_flags: List[str]
) -> List[Dict]:
    """
    Apply workload balancing guardrails:
    - P3/P4: Skip doctors with >3 pages/hour
    - Any: Penalize doctors with >5 pages/hour
    - Consecutive paging protection: Don't page same doctor twice in 5 min
    """
    filtered = []
    
    for cand in candidates:
        doctor_id = cand.get("id")
        page_count = cand.get("page_count_1hr", 0)
        recent_5min = get_recent_page_count(doctor_id, 5)
        
        # Consecutive paging protection - always enforce
        if recent_5min > 0:
            cand["_consecutive_page_flag"] = True
            cand["_score"] = cand.get("_score", 0.5) * 0.5  # Heavy penalty
        
        # Page load limits based on priority
        if priority in ("P3", "P4") and page_count > 3:
            if "enforce_page_load_limit" in guardrail_flags:
                continue  # Skip this candidate
            else:
                cand["_score"] = cand.get("_score", 0.5) * 0.7
        
        # Heavy load penalty for all priorities
        if page_count > 5:
            cand["_score"] = cand.get("_score", 0.5) * 0.6
            cand["_heavy_load_flag"] = True
        
        filtered.append(cand)
    
    return filtered

def apply_zone_escalation(
    candidates: List[Dict],
    priority: str,
    target_zone: str
) -> List[Dict]:
    """
    Zone-based escalation: For P1/P2, boost candidates in/near target zone.
    For critical zones (ICU, OR), require on-call status.
    """
    critical_zones = {"icu", "or_1", "or_2", "ed"}
    is_critical_zone = target_zone.lower() in critical_zones or \
                       any(cz in target_zone.lower() for cz in critical_zones)
    
    for cand in candidates:
        cand_zone = cand.get("zone", "").lower()
        on_call = cand.get("on_call", False)
        
        # Critical zone guardrail: must be on-call
        if is_critical_zone and priority in ("P1", "P2"):
            if not on_call:
                cand["_score"] = cand.get("_score", 0.5) * 0.3
                cand["_off_shift_critical"] = True
        
        # Zone proximity boost for urgent cases
        if priority in ("P1", "P2"):
            if cand_zone == target_zone.lower():
                cand["_score"] = min(1.0, cand.get("_score", 0.5) * 1.3)
            elif cand_zone in critical_zones:
                cand["_score"] = min(1.0, cand.get("_score", 0.5) * 1.1)
    
    return candidates

def distribute_load_among_top_candidates(
    candidates: List[Dict],
    n_top: int = 3
) -> List[Dict]:
    """
    Load distribution: If top candidates have similar scores and similar loads,
    rotate to distribute work. Prevents always paging the same "best" doctor.
    """
    if len(candidates) < 2:
        return candidates
    
    # Sort by score
    sorted_cands = sorted(candidates, key=lambda x: x.get("_score", 0), reverse=True)
    top_n = sorted_cands[:n_top]
    
    if len(top_n) < 2:
        return candidates
    
    # Check if scores are close (within 10%)
    top_score = top_n[0].get("_score", 0)
    close_candidates = [
        c for c in top_n 
        if abs(c.get("_score", 0) - top_score) / max(top_score, 0.01) < 0.1
    ]
    
    if len(close_candidates) < 2:
        return candidates
    
    # Among close candidates, prefer lower page_count
    close_candidates.sort(key=lambda x: (
        x.get("page_count_1hr", 0),
        -x.get("_score", 0)  # Tie-breaker: higher score
    ))
    
    # Reorder: best load balance first, keep rest
    reordered = close_candidates + [c for c in sorted_cands if c not in close_candidates]
    
    return reordered


async def process_alert(alert: OurAlertMessage) -> DispatchDecision:
    """
    Async pipeline with backend integration for speed.
    
    For urgent (P1/P2): Parallel fetching, short timeouts, fast path
    For routine (P3/P4): Can tolerate slight latency for richer context
    """
    from agents.backend_client import get_backend_client
    
    backend = get_backend_client()
    priority = None  # Will be set after classification
    
    # Load configurations
    autonomy_config = load_autonomy_config()
    
    # Step 1: Classify priority (always fast, local)
    priority_resp = priority_classify(alert)
    priority = priority_resp.priority
    is_urgent = priority in ("P1", "P2")
    
    # Step 2: Determine target zone
    target_zone = get_zone_from_room(alert.room) if alert.room else "nurses_station"
    
    # Step 3: EHR Lookup via backend API (async, with priority-based timeout)
    ehr_data = None
    ehr_matched = False
    room_data = None
    
    if alert.room:
        try:
            # Use backend client which has priority-aware timeouts
            ehr_data = await backend.lookup_ehr_by_room(alert.room, priority)
            if ehr_data:
                ehr_matched = True
                # Also fetch room details for zone info
                room_data = await backend.get_room(alert.room, priority)
        except Exception:
            # Fallback: continue without EHR on timeout/error
            pass
    
    if ehr_data:
        # Enhance alert with EHR context
        if not alert.specialty_hint and ehr_data.get("assigned_team"):
            alert.specialty_hint = ehr_data["assigned_team"][0] if ehr_data["assigned_team"] else None
    
    # Step 4: Determine autonomy mode based on policies
    autonomy_mode, zone_policy_reason = determine_autonomy_mode(
        autonomy_config, priority, target_zone, ehr_data
    )
    
    # Step 5: Fetch live doctors from backend (cached for non-urgent)
    try:
        doctors = await backend.get_all_doctors(use_cache=not is_urgent)
        # Convert to dict for easy lookup
        doctors_map = {d["id"]: d for d in doctors}
    except Exception:
        # Fallback to local TinyDB
        db = TinyDB(DB_PATH)
        doctors_map = {doc["id"]: dict(doc) for doc in db.all()}
    
    # Step 6: Query and score candidates (using live data)
    specialties = build_specialty_query(alert)
    
    # If EHR shows primary physician, prioritize their specialty
    if ehr_data and ehr_data.get("assigned_team"):
        for team_specialty in ehr_data["assigned_team"]:
            if team_specialty not in specialties:
                specialties.append(team_specialty)
    
    # Filter doctors by specialty from live backend data
    candidates = []
    for doc_id, doc in doctors_map.items():
        doc_specialties = doc.get("specialty", [])
        if any(s in doc_specialties for s in specialties):
            candidates.append(doc)
    
    if not candidates:
        # Emergency fallback
        for doc_id, doc in doctors_map.items():
            doc_specialties = doc.get("specialty", [])
            if any(s in doc_specialties for s in ["emergency_medicine", "internal_medicine", "surgery"]):
                candidates.append(doc)
    
    # Apply scoring
    scored = score_candidates(candidates, target_zone, priority_resp.guardrail_flags)
    
    # Step 6b: Apply enhanced guardrails
    scored = apply_workload_guardrails(scored, priority, priority_resp.guardrail_flags)
    scored = apply_zone_escalation(scored, priority, target_zone)
    scored = distribute_load_among_top_candidates(scored, n_top=3)
    
    # Step 7: Check for time-queued option (use backend schedules if available)
    time_queued = False
    estimated_dispatch_time = None
    
    # Try to get schedules from backend or local
    schedules = {}
    try:
        # For now, use local schedules - backend doesn't have schedule endpoint yet
        schedules = load_clinician_schedules()
    except:
        pass
    
    future_available = find_future_available_clinicians(scored, schedules, max_wait_minutes=30)
    
    # Step 8: Rank with ASI-1 or fallback
    case_resp = rank_with_asi1(alert, scored, priority)
    if case_resp is None:
        case_resp = fallback_rank(scored)
    
    case_resp.specialty_query = specialties
    
    # Step 9: Handle time-queued dispatch if no one immediately available
    selected = case_resp.candidates[0] if case_resp.candidates else None
    
    if not selected or (future_available and future_available[0][1] > datetime.now()):
        if future_available and autonomy_mode == "autonomous":
            best_future = future_available[0]
            selected_cand = best_future[0]
            selected_eta = best_future[1]
            
            from agents.models import CandidateClinician
            selected = CandidateClinician(
                id=selected_cand["id"],
                name=selected_cand["name"],
                score=selected_cand.get("_score", 0.5),
                reasoning=f"Will be available at {selected_eta.strftime('%H:%M')}",
                specialty=selected_cand.get("specialty", []),
                zone=selected_cand.get("zone"),
                on_call=selected_cand.get("on_call", False),
                page_count_1hr=selected_cand.get("page_count_1hr", 0),
                eta_minutes=None
            )
            time_queued = True
            estimated_dispatch_time = selected_eta.isoformat()
    
    backup_ids = [c.id for c in case_resp.candidates[1:3]] if len(case_resp.candidates) > 1 else []
    
    # Step 10: Determine if review needed
    needs_review = autonomy_mode == "review"
    
    if autonomy_mode == "autonomous":
        needs_review = (
            len(case_resp.candidates) == 0 or
            (len(case_resp.candidates) > 1 and 
             abs(case_resp.candidates[0].score - case_resp.candidates[1].score) < 0.05)
        )
    else:
        needs_review = needs_review or "ambiguous_needs_review" in priority_resp.guardrail_flags
    
    # Step 11: Build reasoning and ACTUALLY PAGE via backend
    page_result = None
    if selected:
        mode_str = "TIME-QUEUED" if time_queued else "IMMEDIATE"
        user_prompt = SYSTEM_PROMPT_SYNTHESIZE.format(
            alert_text=alert.raw_text,
            priority=priority_resp.priority,
            candidate_name=selected.name,
            candidate_id=selected.id,
            score=selected.score,
            candidate_reasoning=selected.reasoning,
            eta=selected.eta_minutes or "unknown",
        )
        raw = asi1_chat("You are a hospital paging operator. Be concise.", user_prompt)
        if raw:
            final_reasoning = raw.strip().replace('"', '').replace("'", "")[:200]
        else:
            action = "Queued" if time_queued else "Dispatched"
            final_reasoning = f"{action} {selected.name} ({selected.id}) — {selected.reasoning}"
            if time_queued:
                final_reasoning += f" [Available at {estimated_dispatch_time[11:16]}]"
        
        # ACTUALLY TRIGGER THE PAGE via backend API with queue manager
        if not time_queued:  # Only page immediately if not time-queued
            try:
                patient_id = ehr_data.get("patient_id") if ehr_data else None
                
                # Create backup doctors list from case response
                backup_doctors = case_resp.candidates[1:] if len(case_resp.candidates) > 1 else []
                backup_ids = [b.id for b in backup_doctors]
                
                # Create page via backend with backup doctors for escalation
                page_result = await backend.create_page(
                    doctor_id=selected.id,
                    priority=priority,
                    message=alert.raw_text,
                    room=alert.room,
                    patient_id=patient_id,
                    requested_by=alert.requested_by
                )
                # Record the page attempt for consecutive paging protection
                record_page_attempt(selected.id)
                
                # Add to queue manager for timeout tracking and auto-escalation
                queue_mgr = get_queue_manager()
                queue_id = await queue_mgr.add_page(
                    decision=DispatchDecision(
                        alert=alert,
                        priority=priority_resp.priority,
                        selected_clinician_id=selected.id,
                        selected_clinician_name=selected.name,
                        backup_clinician_ids=backup_ids,
                        reasoning=final_reasoning,
                        mode=detect_mode(alert.raw_text),
                        needs_operator_review=needs_review,
                        guardrail_flags=priority_resp.guardrail_flags,
                        autonomy_mode=autonomy_mode,
                        zone_policy_applied=zone_policy_reason,
                        ehr_matched=ehr_matched,
                        time_queued=time_queued,
                        estimated_dispatch_time=estimated_dispatch_time,
                        details={
                            "case_handler_reasoning": case_resp.reasoning,
                            "priority_handler_reasoning": priority_resp.reasoning,
                            "candidates_count": len(case_resp.candidates),
                            "specialty_query": specialties,
                            "ehr_patient": ehr_data.get("name") if ehr_data else None,
                            "ehr_primary_physician": ehr_data.get("primary_physician") if ehr_data else None,
                        }
                    ),
                    backup_doctors=backup_doctors,
                    page_result=page_result
                )
                final_reasoning += f" [Queue: {queue_id}]"
                
            except Exception as e:
                page_result = {"error": str(e), "status": "failed"}
                final_reasoning += f" [PAGE FAILED: {e}]"
    else:
        final_reasoning = "No suitable candidates found — requires operator intervention"
    
    return DispatchDecision(
        alert=alert,
        priority=priority_resp.priority,
        selected_clinician_id=selected.id if selected else None,
        selected_clinician_name=selected.name if selected else None,
        backup_clinician_ids=backup_ids,
        reasoning=final_reasoning,
        mode=detect_mode(alert.raw_text),
        needs_operator_review=needs_review,
        guardrail_flags=priority_resp.guardrail_flags,
        autonomy_mode=autonomy_mode,
        zone_policy_applied=zone_policy_reason,
        ehr_matched=ehr_matched,
        time_queued=time_queued,
        estimated_dispatch_time=estimated_dispatch_time,
        details={
            "case_handler_reasoning": case_resp.reasoning,
            "priority_handler_reasoning": priority_resp.reasoning,
            "candidates_count": len(case_resp.candidates),
            "specialty_query": specialties,
            "ehr_patient": ehr_data.get("name") if ehr_data else None,
            "ehr_primary_physician": ehr_data.get("primary_physician") if ehr_data else None,
        },
    )


def format_dispatch_response(decision: DispatchDecision) -> str:
    """Format DispatchDecision as human-readable chat response."""
    emoji = "🚨" if decision.priority in ["P1", "P2"] else "📟"
    mode_str = "SPARSE" if decision.mode == "sparse" else "RICH"
    autonomy_emoji = "🤖" if decision.autonomy_mode == "autonomous" else "👁️"
    
    # Check if this is in a queue
    queue_info = ""
    if decision.reasoning and "[Queue:" in decision.reasoning:
        # Extract queue ID
        import re
        match = re.search(r'\[Queue: ([^\]]+)\]', decision.reasoning)
        if match:
            queue_id = match.group(1)
            queue_info = f"\n📋 Queue ID: {queue_id} (auto-escalation enabled)"
    
    lines = [
        f"{emoji} DISPATCH DECISION ({mode_str} MODE)",
        f"{autonomy_emoji} Autonomy: {decision.autonomy_mode.upper()}{queue_info}",
        f"",
        f"Priority: {decision.priority}",
        f"Alert: {decision.alert.raw_text[:60]}...",
    ]
    
    # EHR info if matched
    if decision.ehr_matched:
        patient = decision.details.get("ehr_patient", "Unknown")
        primary = decision.details.get("ehr_primary_physician", "None")
        lines.extend([
            f"",
            f"📋 EHR Match: {patient}",
            f"👤 Primary: {primary}",
        ])
    
    if decision.selected_clinician_name:
        lines.extend([
            f"",
            f"📍 Assigned: {decision.selected_clinician_name} ({decision.selected_clinician_id})",
            f"📝 Reasoning: {decision.reasoning}",
        ])
    else:
        lines.append(f"⚠️ No clinician assigned — manual intervention required")
    
    if decision.backup_clinician_ids:
        lines.append(f"📋 Backup: {', '.join(decision.backup_clinician_ids)}")
    
    if decision.guardrail_flags:
        lines.append(f"🛡️ Flags: {', '.join(decision.guardrail_flags)}")
    
    if decision.needs_operator_review:
        lines.append(f"🔍 REQUIRES OPERATOR REVIEW")
    
    return "\n".join(lines)


@agent.on_event("startup")
async def _startup(ctx: Context):
    ctx.logger.info(f"[operator] address={agent.address}")
    ctx.logger.info(f"[operator] Chat Protocol enabled for ASI:One")
    ctx.logger.info(f"[operator] mode=ASYNC with backend integration")
    ctx.logger.info(f"[operator] Enhanced guardrails: workload balancing, zone escalation, consecutive paging protection")
    ctx.logger.info(f"[operator] Queue manager: auto-escalation with timeout handling")
    
    # Start the queue manager for auto-escalation
    queue_mgr = get_queue_manager()
    await queue_mgr.start()
    ctx.logger.info(f"[operator] Queue manager started")


# Simple text response model since ChatResponse doesn't exist in the protocol
class SimpleTextResponse(Model):
    content: str


@agent.on_message(model=ChatMessage, replies=SimpleTextResponse)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage):
    """Handle incoming chat from ASI:One / Agentverse — async processing with backend integration."""
    ctx.logger.info(f"[operator] chat from {sender[:16]}...: {msg.content!r}")
    
    raw_text = msg.content or ""
    room = extract_room(raw_text)
    specialty_hint = extract_specialty_hint(raw_text)
    mode = detect_mode(raw_text)
    
    ctx.logger.info(f"[operator] mode={mode}, room={room}, hint={specialty_hint}")
    
    alert = OurAlertMessage(
        raw_text=raw_text,
        room=room,
        specialty_hint=specialty_hint,
        mode=mode,
        requested_by=sender,
    )
    
    # Async pipeline with backend integration
    try:
        decision = await process_alert(alert)
        response_text = format_dispatch_response(decision)
        ctx.logger.info(f"[operator] dispatched to {decision.selected_clinician_id or 'NONE'}")
    except Exception as e:
        ctx.logger.error(f"[operator] ERROR: {e}")
        import traceback
        ctx.logger.error(traceback.format_exc())
        response_text = f"⚠️ Processing error: {e}"
    
    await ctx.send(sender, SimpleTextResponse(content=response_text))


@agent.on_message(model=ChatAcknowledgement)
async def handle_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"[operator] ack from {sender[:12]}")


if __name__ == "__main__":
    agent.run()

