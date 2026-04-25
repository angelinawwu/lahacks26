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
from tinydb import TinyDB
from datetime import datetime, timedelta
from typing import Tuple

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


def process_alert(alert: OurAlertMessage) -> DispatchDecision:
    """Synchronous pipeline: classify priority, query cases, synthesize decision."""
    
    # Load configurations
    autonomy_config = load_autonomy_config()
    
    # Step 1: Classify priority
    priority_resp = priority_classify(alert)
    
    # Step 2: Determine target zone
    target_zone = get_zone_from_room(alert.room) if alert.room else "nurses_station"
    
    # Step 3: EHR Lookup for patient context
    ehr_data = lookup_ehr_by_room(alert.room) if alert.room else None
    ehr_matched = ehr_data is not None
    
    if ehr_data:
        # Enhance alert with EHR context
        if not alert.specialty_hint and ehr_data.get("assigned_team"):
            alert.specialty_hint = ehr_data["assigned_team"][0] if ehr_data["assigned_team"] else None
    
    # Step 4: Determine autonomy mode based on policies
    autonomy_mode, zone_policy_reason = determine_autonomy_mode(
        autonomy_config, priority_resp.priority, target_zone, ehr_data
    )
    
    # Step 5: Query and score candidates
    db = TinyDB(DB_PATH)
    specialties = build_specialty_query(alert)
    
    # If EHR shows primary physician, prioritize their specialty
    if ehr_data and ehr_data.get("assigned_team"):
        # Add EHR team specialties to query
        for team_specialty in ehr_data["assigned_team"]:
            if team_specialty not in specialties:
                specialties.append(team_specialty)
    
    candidates = query_clinicians(db, specialties)
    
    if not candidates:
        # Emergency fallback
        candidates = query_clinicians(db, ["emergency_medicine", "internal_medicine", "surgery"])
    
    scored = score_candidates(candidates, target_zone, priority_resp.guardrail_flags)
    
    # Step 6: Check for time-queued option (clinicians available soon)
    schedules = load_clinician_schedules()
    future_available = find_future_available_clinicians(scored, schedules, max_wait_minutes=30)
    
    time_queued = False
    estimated_dispatch_time = None
    
    # Step 7: Rank with ASI-1 or fallback
    case_resp = rank_with_asi1(alert, scored, priority_resp.priority)
    if case_resp is None:
        case_resp = fallback_rank(scored)
    
    case_resp.specialty_query = specialties
    
    # Step 8: Handle time-queued dispatch if no one immediately available
    selected = case_resp.candidates[0] if case_resp.candidates else None
    
    if not selected or (future_available and future_available[0][1] > datetime.now()):
        # Check if we should time-queue
        if future_available and autonomy_mode == "autonomous":
            # In autonomous mode, schedule for next available
            best_future = future_available[0]
            selected_cand = best_future[0]
            selected_eta = best_future[1]
            
            # Create a mock CandidateClinician for the time-queued person
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
    
    # Step 9: Determine if review needed based on autonomy mode
    needs_review = autonomy_mode == "review"  # Zone or priority policy forces review
    
    if autonomy_mode == "autonomous":
        # In autonomous mode, only review on critical issues
        needs_review = (
            len(case_resp.candidates) == 0 or
            (len(case_resp.candidates) > 1 and 
             abs(case_resp.candidates[0].score - case_resp.candidates[1].score) < 0.05)  # Very close tie
        )
    else:
        # In review mode, also flag ambiguous
        needs_review = needs_review or "ambiguous_needs_review" in priority_resp.guardrail_flags
    
    # Step 10: Build reasoning
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
    
    lines = [
        f"{emoji} DISPATCH DECISION ({mode_str} MODE)",
        f"{autonomy_emoji} Autonomy: {decision.autonomy_mode.upper()}",
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
    ctx.logger.info(f"[operator] mode=SYNC (direct function calls)")


# Simple text response model since ChatResponse doesn't exist in the protocol
class SimpleTextResponse(Model):
    content: str


@agent.on_message(model=ChatMessage, replies=SimpleTextResponse)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage):
    """Handle incoming chat from ASI:One / Agentverse — synchronous processing."""
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
    
    # Synchronous pipeline
    try:
        decision = process_alert(alert)
        response_text = format_dispatch_response(decision)
        ctx.logger.info(f"[operator] dispatched to {decision.selected_clinician_id or 'NONE'}")
    except Exception as e:
        ctx.logger.error(f"[operator] ERROR: {e}")
        response_text = f"⚠️ Processing error: {e}"
    
    await ctx.send(sender, SimpleTextResponse(content=response_text))


@agent.on_message(model=ChatAcknowledgement)
async def handle_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"[operator] ack from {sender[:12]}")


if __name__ == "__main__":
    agent.run()

