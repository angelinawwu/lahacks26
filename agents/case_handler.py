"""
Case Handler Agent.

Receives an AlertMessage and a priority level, queries TinyDB for clinicians
matching the required specialty, scores by availability/location/caseload,
and uses ASI-1 Mini to rank top candidates with plain-language reasoning.

Implements zone-based travel time estimation per WiFi-location requirement.
"""
from __future__ import annotations
import json
import os
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from uagents import Agent, Context
from tinydb import TinyDB, Query

from agents.models import AlertMessage, PriorityResponse, CaseResponse, CandidateClinician
from agents.asi_client import asi1_chat, extract_json

load_dotenv()

SEED = os.getenv("CASE_SEED", "case-handler-dev-seed")
PORT = int(os.getenv("CASE_PORT", "8003"))
DB_PATH = os.getenv("CLINICIANS_DB", "db/clinicians.json")

agent = Agent(
    name="case_handler",
    seed=SEED,
    port=PORT,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)

# Zone travel time map (minutes) per WiFi-location requirement
ZONE_TRAVEL_MINUTES: Dict[tuple[str, str], float] = {
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

SYSTEM_PROMPT = """You are the Case Handler in a hospital paging system.

You receive a clinical alert and a list of available clinician candidates.
Rank the TOP 3 candidates best suited to respond, and write a ONE SENTENCE
plain-language explanation for each.

Scoring factors (in order of importance):
1. Specialty match to the alert (critical)
2. Travel time / proximity to the patient location (critical)
3. Current caseload (prefer fewer active cases)
4. Page load in last hour (prefer fewer recent pages)
5. On-call status (prefer on-call clinicians)

Response format — JSON ONLY, no prose:
{
  "candidates": [
    {"id": "dr_chen", "score": 0.95, "reasoning": "Cardiology specialist, in same zone, moderate caseload"},
    {"id": "dr_rodriguez", "score": 0.82, "reasoning": "Cardiology + IM, nearby in ICU, currently managing 2 cases"},
    {"id": "dr_patel", "score": 0.71, "reasoning": "Emergency medicine, 2 min away, experienced with cardiac emergencies"}
  ],
  "reasoning": "One sentence summary of selection logic"
}
"""

# Specialty fallback mapping for sparse/emergency mode
SPECIALTY_EXPAND: Dict[str, List[str]] = {
    "cardiac": ["cardiology", "internal_medicine", "emergency_medicine"],
    "heart": ["cardiology", "internal_medicine", "emergency_medicine"],
    "chest pain": ["cardiology", "emergency_medicine", "internal_medicine"],
    "stroke": ["neurology", "emergency_medicine"],
    "brain": ["neurology", "emergency_medicine"],
    "seizure": ["neurology", "emergency_medicine"],
    "trauma": ["trauma", "emergency_medicine", "surgery"],
    "bleeding": ["trauma", "emergency_medicine", "surgery"],
    "surgery": ["surgery", "trauma"],
    "or": ["surgery", "anesthesiology"],
    "help": ["emergency_medicine", "internal_medicine"],
}


def get_travel_minutes(from_zone: str, to_zone: str) -> float:
    """Return estimated travel time between zones."""
    if from_zone == to_zone:
        return 0.5
    # Check both directions
    minutes = ZONE_TRAVEL_MINUTES.get((from_zone, to_zone))
    if minutes is None:
        minutes = ZONE_TRAVEL_MINUTES.get((to_zone, from_zone))
    return minutes if minutes is not None else 3.0


def build_specialty_query(alert: AlertMessage) -> List[str]:
    """Determine specialties to query, with emergency fallback expansion."""
    text = (alert.raw_text or "").lower()
    hint = (alert.specialty_hint or "").lower()
    
    # If explicit hint provided, use it
    if hint:
        return [hint]
    
    # Check for keyword matches
    for keyword, specialties in SPECIALTY_EXPAND.items():
        if keyword in text:
            return specialties
    
    # Default: broad emergency medicine search for ambiguous cases
    return ["emergency_medicine", "internal_medicine"]


def query_clinicians(db: TinyDB, specialties: List[str], 
                     require_available: bool = True) -> List[Dict[str, Any]]:
    """Query TinyDB for clinicians matching criteria."""
    Clinician = Query()
    
    # Base query: not off_shift (unless explicitly on_call for high priority)
    base_query = Clinician.status != "off_shift"
    
    # Specialty match (any of the listed specialties)
    specialty_query = Clinician.specialty.any(specialties)
    
    # Combined query
    results = db.search(base_query & specialty_query)
    
    # Filter out in_procedure unless they're on_call and it's urgent
    available = []
    for r in results:
        if r.get("status") == "in_procedure" and not r.get("on_call"):
            continue
        available.append(r)
    
    return available


def score_candidates(candidates: List[Dict], target_zone: str, 
                     flags: List[str]) -> List[Dict]:
    """Score and enrich candidates with metadata."""
    scored = []
    
    for c in candidates:
        # Base score
        score = 0.5
        
        # Travel time penalty/bonus
        travel = get_travel_minutes(c.get("zone", ""), target_zone)
        if travel <= 1:
            score += 0.25
        elif travel <= 3:
            score += 0.15
        elif travel <= 5:
            score += 0.05
        else:
            score -= 0.1
        
        # Caseload penalty
        active = c.get("active_cases", 0)
        if active == 0:
            score += 0.15
        elif active <= 2:
            score += 0.05
        else:
            score -= 0.1
        
        # Page load penalty (guardrail-aware)
        pages = c.get("page_count_1hr", 0)
        if pages == 0:
            score += 0.1
        elif pages <= 2:
            score += 0.0
        elif pages > 3 and "enforce_page_load_limit" in flags:
            score -= 0.3  # Heavy penalty
        else:
            score -= 0.1
        
        # On-call bonus
        if c.get("on_call"):
            score += 0.1
        
        # In-procedure penalty (still available if on_call, but less ideal)
        if c.get("status") == "in_procedure":
            score -= 0.2
        
        c["_score"] = min(0.99, max(0.1, score))
        c["_eta"] = travel
        scored.append(c)
    
    # Sort by score descending
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def rank_with_asi1(alert: AlertMessage, candidates: List[Dict], 
                   priority: str) -> Optional[CaseResponse]:
    """Use ASI-1 Mini to rank top 3 candidates with reasoning."""
    if not candidates:
        return None
    
    # Take top 5 for ASI-1 to choose from
    top_input = candidates[:5]
    
    user_prompt = json.dumps({
        "alert": alert.raw_text,
        "room": alert.room,
        "priority": priority,
        "candidates": [
            {
                "id": c["id"],
                "name": c["name"],
                "specialty": c.get("specialty", []),
                "zone": c.get("zone"),
                "on_call": c.get("on_call"),
                "page_count_1hr": c.get("page_count_1hr"),
                "active_cases": c.get("active_cases"),
                "computed_score": c.get("_score"),
                "eta_minutes": c.get("_eta"),
            }
            for c in top_input
        ]
    }, default=str)
    
    raw = asi1_chat(SYSTEM_PROMPT, user_prompt)
    parsed = extract_json(raw) if raw else None
    
    if parsed and "candidates" in parsed:
        candidates_out = []
        for c in parsed["candidates"]:
            # Find matching full record
            full = next((x for x in top_input if x["id"] == c.get("id")), None)
            if full:
                candidates_out.append(CandidateClinician(
                    id=full["id"],
                    name=full["name"],
                    score=c.get("score", full.get("_score", 0.5)),
                    reasoning=c.get("reasoning", "ASI-1 ranked"),
                    specialty=full.get("specialty", []),
                    zone=full.get("zone"),
                    on_call=full.get("on_call", False),
                    page_count_1hr=full.get("page_count_1hr", 0),
                    eta_minutes=full.get("_eta"),
                ))
        
        return CaseResponse(
            candidates=candidates_out,
            specialty_query=[],
            total_available=len(candidates),
            reasoning=parsed.get("reasoning", "ASI-1 ranking completed"),
            fallback_used=False,
        )
    
    return None


def fallback_rank(candidates: List[Dict]) -> CaseResponse:
    """Deterministic fallback when ASI-1 is unavailable."""
    top = candidates[:3]
    candidates_out = []
    
    for c in top:
        reasoning_parts = []
        if c.get("_score", 0) > 0.7:
            reasoning_parts.append("high computed score")
        if c.get("_eta", 99) <= 2:
            reasoning_parts.append("close proximity")
        if c.get("on_call"):
            reasoning_parts.append("on-call status")
        
        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "computed heuristic rank"
        
        candidates_out.append(CandidateClinician(
            id=c["id"],
            name=c["name"],
            score=c.get("_score", 0.5),
            reasoning=reasoning,
            specialty=c.get("specialty", []),
            zone=c.get("zone"),
            on_call=c.get("on_call", False),
            page_count_1hr=c.get("page_count_1hr", 0),
            eta_minutes=c.get("_eta"),
        ))
    
    return CaseResponse(
        candidates=candidates_out,
        specialty_query=[],
        total_available=len(candidates),
        reasoning=f"Fallback ranking: selected top {len(top)} candidates by heuristic scoring (ASI-1 unavailable)",
        fallback_used=True,
    )


from uagents import Model as _Model


class CaseHandlerRequest(_Model):
    """Internal message format from Operator to Case Handler."""
    alert: AlertMessage
    priority: str
    guardrail_flags: List[str] = []


@agent.on_event("startup")
async def _startup(ctx: Context):
    ctx.logger.info(f"[case_handler] address={agent.address}")
    ctx.logger.info(f"[case_handler] db={DB_PATH}")


@agent.on_message(model=CaseHandlerRequest, replies=CaseResponse)
async def handle_case(ctx: Context, sender: str, msg: CaseHandlerRequest):
    ctx.logger.info(f"[case_handler] case from {sender[:12]}…: {msg.alert.raw_text!r}")
    
    # Load database
    db = TinyDB(DB_PATH)
    
    # Determine target zone from alert room
    target_zone = msg.alert.room.lower().replace(" ", "_") if msg.alert.room else "nurses_station"
    # Map common room patterns to zones
    zone_map = {
        "room_412": "floor_3_corridor",
        "room_301": "icu",
        "room_201": "nurses_station",
        "or": "or_1",
    }
    for pattern, zone in zone_map.items():
        if pattern in target_zone:
            target_zone = zone
            break
    
    # Build specialty query with emergency fallback
    specialties = build_specialty_query(msg.alert)
    ctx.logger.info(f"[case_handler] querying specialties: {specialties}, target_zone: {target_zone}")
    
    # Query available clinicians
    candidates = query_clinicians(db, specialties)
    ctx.logger.info(f"[case_handler] found {len(candidates)} candidates")
    
    if not candidates:
        # Emergency fallback: query ANY available clinician
        ctx.logger.warning("[case_handler] NO candidates found, emergency fallback to any available")
        candidates = query_clinicians(db, ["emergency_medicine", "internal_medicine", "surgery", "anesthesiology"])
    
    # Score candidates
    scored = score_candidates(candidates, target_zone, msg.guardrail_flags)
    
    # Rank with ASI-1 or fallback
    resp = rank_with_asi1(msg.alert, scored, msg.priority)
    if resp is None:
        resp = fallback_rank(scored)
    
    resp.specialty_query = specialties
    
    ctx.logger.info(
        f"[case_handler] reasoning: {resp.reasoning} | "
        f"candidates={[c.id for c in resp.candidates]} fallback={resp.fallback_used}"
    )
    
    await ctx.send(sender, resp)


if __name__ == "__main__":
    agent.run()
