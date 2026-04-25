"""
Shared message models for the MedPage multi-agent paging system.

All agents (Operator, Priority Handler, Case Handler) exchange these
structured messages over uAgents. Keep this file as the single source of
truth for inter-agent schemas.
"""
from typing import List, Optional, Dict, Any
from uagents import Model


# ---------------------------------------------------------------------------
# Inbound alert
# ---------------------------------------------------------------------------
class AlertMessage(Model):
    """
    A clinical alert as received (or parsed) by the Operator Agent.

    `raw_text` is whatever the operator / ASI:One user typed. The other
    fields are best-effort extractions — any of them may be None in
    sparse / emergency mode, and downstream agents must tolerate that.
    """
    raw_text: str
    room: Optional[str] = None
    specialty_hint: Optional[str] = None          # e.g. "cardiology"
    symptoms: Optional[str] = None                # free-text symptom summary
    patient_id: Optional[str] = None
    mode: Optional[str] = None                    # "sparse" | "rich"
    requested_by: Optional[str] = None            # operator / nurse id


# ---------------------------------------------------------------------------
# Priority Handler response
# ---------------------------------------------------------------------------
class PriorityResponse(Model):
    """
    Output of the Priority Handler Agent.

    `priority` is one of "P1" | "P2" | "P3" | "P4".
    `guardrail_flags` is a list of short machine-readable flags such as
    "off_shift_suppressed", "page_load_exceeded", "ambiguous_needs_review".
    """
    priority: str
    guardrail_flags: List[str] = []
    reasoning: str
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Case Handler response
# ---------------------------------------------------------------------------
class CandidateClinician(Model):
    id: str
    name: str
    score: float
    reasoning: str
    specialty: List[str] = []
    zone: Optional[str] = None
    on_call: bool = False
    page_count_1hr: int = 0
    eta_minutes: Optional[float] = None


class CaseResponse(Model):
    """
    Output of the Case Handler Agent: top ranked candidates plus metadata
    about the query used to find them.
    """
    candidates: List[CandidateClinician] = []
    specialty_query: List[str] = []
    total_available: int = 0
    reasoning: str = ""
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Autonomy Configuration
# ---------------------------------------------------------------------------
class ZonePolicy(Model):
    mode: str  # "review" | "autonomous"
    reason: str


class AutonomyConfig(Model):
    global_mode: str  # "review" | "autonomous"
    zone_policies: Dict[str, ZonePolicy] = {}
    priority_policies: Dict[str, ZonePolicy] = {}


# ---------------------------------------------------------------------------
# EHR and Patient Data
# ---------------------------------------------------------------------------
class EHRRecord(Model):
    patient_id: str
    name: str
    room: str
    primary_diagnosis: str
    comorbidities: List[str] = []
    assigned_team: List[str] = []
    primary_physician: Optional[str] = None
    ehr_access_level: str = "full"  # full | limited | emergency_only


# ---------------------------------------------------------------------------
# Clinician Schedule for Time-Queued Matching
# ---------------------------------------------------------------------------
class ScheduledProcedure(Model):
    start: str  # ISO timestamp
    end: str  # ISO timestamp
    type: str
    location: str


class ClinicianSchedule(Model):
    clinician_id: str
    status: str  # available | in_procedure | off_shift
    procedure_end_time: Optional[str] = None
    next_available_eta: Optional[str] = None
    scheduled_procedures: List[ScheduledProcedure] = []
    shift_end: Optional[str] = None


# ---------------------------------------------------------------------------
# Final dispatch decision (Operator Agent output)
# ---------------------------------------------------------------------------
class DispatchDecision(Model):
    """
    Final, human-readable dispatch decision produced by the Operator
    Agent. This is what gets surfaced to the UI / ASI:One user.
    """
    alert: AlertMessage
    priority: str
    selected_clinician_id: Optional[str] = None
    selected_clinician_name: Optional[str] = None
    backup_clinician_ids: List[str] = []
    reasoning: str
    mode: str = "rich"
    needs_operator_review: bool = False
    guardrail_flags: List[str] = []
    autonomy_mode: str = "review"  # which mode was applied
    zone_policy_applied: Optional[str] = None  # reason if zone-specific policy triggered
    ehr_matched: bool = False  # whether EHR data was used
    time_queued: bool = False  # whether this is a delayed dispatch
    estimated_dispatch_time: Optional[str] = None  # ISO timestamp if time-queued
    details: Dict[str, Any] = {}                  # any extra debug info
