"""
Case Handler Agent.

Receives an AlertMessage and a priority level, queries TinyDB for clinicians
matching the required specialty, scores by availability/location/caseload,
and uses ASI-1 Mini to rank top candidates with plain-language reasoning.

Implements zone-based travel time estimation per WiFi-location requirement.
"""
from __future__ import annotations
import json
import logging
import os
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from uagents import Agent, Context
from tinydb import TinyDB, Query

from agents.models import AlertMessage, PriorityResponse, CaseResponse, CandidateClinician
from agents.asi_client import asi1_chat, extract_json
from agents.hospital_graph import travel_minutes, room_to_zone

load_dotenv()

_log = logging.getLogger(__name__)

SEED = os.getenv("CASE_SEED", "case-handler-dev-seed")
PORT = int(os.getenv("CASE_PORT", "8003"))
DB_PATH = os.getenv("CLINICIANS_DB", "db/clinicians.json")

agent = Agent(
    name="case_handler",
    seed=SEED,
    port=PORT,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)


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


def get_zone_from_room(room: str) -> str:
    """Resolve a room identifier to a zone string using the hospital graph."""
    if not room:
        return "nurses_station"
    return room_to_zone(room.strip().lower())


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


# Statuses that mean the clinician cannot be paged. `on_call` doctors who are
# `in_procedure` are still pageable for urgent cases — handled below.
_UNPAGEABLE_STATUSES = {"off_shift", "on_break", "on_case"}


def is_clinician_available(doc: Dict[str, Any], priority: Optional[str] = None) -> bool:
    """
    Return True iff the clinician is currently pageable.

    Available means:
      - status == "available", OR
      - status == "in_procedure" AND on_call AND priority in (P1, P2)
        (an on-call surgeon can break to take an emergency)

    Excluded: off_shift, on_break, on_case, and non-on-call in_procedure.
    """
    status = (doc.get("status") or "").lower()
    if status == "available":
        return True
    if status == "in_procedure" and doc.get("on_call") and priority in ("P1", "P2"):
        return True
    return False


def query_clinicians(db: TinyDB, specialties: List[str],
                     priority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query TinyDB for clinicians matching specialty AND currently available."""
    Clinician = Query()
    specialty_query = Clinician.specialty.any(specialties)
    results = db.search(specialty_query)
    return [r for r in results if is_clinician_available(r, priority)]


def score_candidates(candidates: List[Dict], target_zone: str, 
                     flags: List[str]) -> List[Dict]:
    """Score and enrich candidates with metadata."""
    scored = []
    
    for c in candidates:
        # Base score
        score = 0.5
        
        # Travel time penalty/bonus (A* pathfinding)
        travel = travel_minutes(c.get("zone", ""), target_zone)
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


def process_case(
    alert: AlertMessage,
    priority: str,
    guardrail_flags: List[str],
) -> CaseResponse:
    """
    Run case resolution (DB query, scoring, ASI-1 or fallback).
    Used by the uAgent handler and the HTTP API.
    """
    db = TinyDB(DB_PATH)

    target_zone = get_zone_from_room(alert.room) if alert.room else "nurses_station"

    specialties = build_specialty_query(alert)
    _log.info(f"[case_handler] querying specialties: {specialties}, target_zone: {target_zone}")

    candidates = query_clinicians(db, specialties, priority)
    # Never page the clinician who raised the alert.
    if alert.requested_by:
        candidates = [c for c in candidates if c.get("id") != alert.requested_by]
    _log.info(f"[case_handler] found {len(candidates)} available candidates")

    if not candidates:
        _log.warning("[case_handler] NO candidates found, emergency fallback to any available")
        candidates = query_clinicians(
            db,
            ["emergency_medicine", "internal_medicine", "surgery", "anesthesiology"],
            priority,
        )
        if alert.requested_by:
            candidates = [c for c in candidates if c.get("id") != alert.requested_by]

    scored = score_candidates(candidates, target_zone, guardrail_flags)
    resp = rank_with_asi1(alert, scored, priority)
    if resp is None:
        resp = fallback_rank(scored)
    resp.specialty_query = specialties
    return resp


@agent.on_event("startup")
async def _startup(ctx: Context):
    ctx.logger.info(f"[case_handler] address={agent.address}")
    ctx.logger.info(f"[case_handler] db={DB_PATH}")


@agent.on_message(model=CaseHandlerRequest, replies=CaseResponse)
async def handle_case(ctx: Context, sender: str, msg: CaseHandlerRequest):
    ctx.logger.info(f"[case_handler] case from {sender[:12]}…: {msg.alert.raw_text!r}")
    resp = process_case(msg.alert, msg.priority, msg.guardrail_flags)
    ctx.logger.info(
        f"[case_handler] reasoning: {resp.reasoning} | "
        f"candidates={[c.id for c in resp.candidates]} fallback={resp.fallback_used}"
    )
    await ctx.send(sender, resp)


if __name__ == "__main__":
    agent.run()
