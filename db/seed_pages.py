"""
Seed db/pages.json (TinyDB) with realistic active + recent pages so the
operator's Alert Feed, Cases Table, and Queue panel populate on first load.

Run from repo root:
    python3 db/seed_pages.py

Idempotent: drops + repopulates the `_default` table each run.
Pages reference real TinyDB clinicians (db/clinicians.json) and EHR records
(db/ehr_records.json).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tinydb import TinyDB

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "pages.json")


def _iso(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _page(
    *,
    doctor_id: str,
    doctor_name: str,
    specialty: list[str],
    room: str | None,
    priority: str,
    status: str,
    message: str,
    title: str,
    reasoning: str,
    seconds_ago: int,
    patient_id: str | None = None,
    backup_doctors: list[str] | None = None,
    responded_seconds_ago: int | None = None,
    outcome: str | None = None,
    escalation_history: list[dict] | None = None,
) -> dict:
    pid = uuid4().hex
    return {
        "id": pid,
        "alert_id": pid,
        "source": "dispatch",
        "doctor_id": doctor_id,
        "patient_id": patient_id,
        "message": message,
        "room": room,
        "priority": priority,
        "status": status,
        "requested_by": "rn_voice_agent",
        "backup_doctors": backup_doctors or [],
        "created_at": _iso(seconds_ago),
        "responded_at": _iso(responded_seconds_ago) if responded_seconds_ago is not None else None,
        "outcome": outcome,
        "escalation_history": escalation_history or [],
        "title": title,
        "assigned_clinician_name": doctor_name,
        "specialty": specialty,
        "ack_deadline_seconds": 60,
        "reasoning": reasoning,
        "guardrail_flags": [],
        "needs_operator_review": False,
        "ehr_matched": patient_id is not None,
        "autonomy_mode": "automated",
        "mode": "auto",
    }


PAGES = [
    # --- Live (paging) — show up in alert feed with running timers ---
    _page(
        doctor_id="dr_chen",
        doctor_name="Dr. Sarah Chen",
        specialty=["cardiology"],
        room="412",
        priority="P1",
        status="paging",
        title="STEMI — chest pain, ST elevation",
        message="STEMI suspected. ST elevation V2-V4. BP 92/58, HR 118. Pt diaphoretic.",
        reasoning="Acute MI presentation; cardiology on-call required within 10 min.",
        patient_id="PT-2024-00412",
        backup_doctors=["dr_rodriguez"],
        seconds_ago=42,
    ),
    _page(
        doctor_id="dr_kim",
        doctor_name="Dr. James Kim",
        specialty=["neurology"],
        room="301",
        priority="P1",
        status="paging",
        title="Stroke alert — left-sided weakness",
        message="Suspected ischemic stroke. NIHSS 14. Last known well 35 min ago. tPA window open.",
        reasoning="Time-critical stroke; neurology consult + imaging now.",
        patient_id="PT-2024-00301",
        backup_doctors=["dr_rodriguez"],
        seconds_ago=18,
    ),
    _page(
        doctor_id="dr_iyer",
        doctor_name="Dr. Nisha Iyer",
        specialty=["emergency_medicine"],
        room="er",
        priority="P2",
        status="paging",
        title="Multi-trauma — MVA",
        message="MVA, 32M, GCS 13, suspected pelvic fracture. ETA 4 min.",
        reasoning="Trauma activation; ED + surgery standby.",
        backup_doctors=["dr_williams", "dr_patel"],
        seconds_ago=86,
    ),
    _page(
        doctor_id="dr_martinez",
        doctor_name="Dr. Carlos Martinez",
        specialty=["pediatrics", "critical_care"],
        room="picu",
        priority="P2",
        status="paging",
        title="PICU desat — 8yo asthma",
        message="SpO2 88% on 6L NC, increased WOB. Albuterol q20 min started.",
        reasoning="Pediatric respiratory distress; critical care intensivist.",
        seconds_ago=130,
    ),

    # --- Escalated (no answer from primary) ---
    _page(
        doctor_id="dr_rodriguez",
        doctor_name="Dr. Miguel Rodriguez",
        specialty=["cardiology", "internal_medicine"],
        room="icu",
        priority="P2",
        status="escalated",
        title="ICU bedside — bradycardia",
        message="HR 38, BP 88/54, asymptomatic. Atropine ordered.",
        reasoning="Symptomatic bradycardia; cardiology bedside review.",
        backup_doctors=["dr_chen"],
        seconds_ago=240,
        escalation_history=[
            {
                "from_doctor": "dr_chen",
                "to_doctor": "dr_rodriguez",
                "timestamp": _iso(180),
                "reason": "no_response_30s",
            }
        ],
    ),

    # --- Pending operator approval (manual mode override) ---
    _page(
        doctor_id="dr_goldberg",
        doctor_name="Dr. Ethan Goldberg",
        specialty=["obstetrics", "gynecology"],
        room="labor_delivery",
        priority="P2",
        status="pending_approval",
        title="L&D — fetal decels",
        message="Late decels, category II tracing, 36w G2P1. Considering c-section.",
        reasoning="Non-reassuring fetal status; OB attending review.",
        seconds_ago=22,
    ),

    # --- Accepted (recent history; shows in cases table & feed) ---
    _page(
        doctor_id="dr_patel",
        doctor_name="Dr. Priya Patel",
        specialty=["emergency_medicine", "trauma"],
        room="er",
        priority="P3",
        status="accepted",
        title="Lac repair — forearm",
        message="6cm laceration, no neurovascular deficit. Needs suture + tetanus.",
        reasoning="Routine ED procedure; on-call EM physician.",
        outcome="accept",
        responded_seconds_ago=420,
        seconds_ago=520,
    ),
    _page(
        doctor_id="dr_harris",
        doctor_name="Dr. Rachel Harris",
        specialty=["pediatrics", "adolescent_medicine"],
        room="teen_center",
        priority="P3",
        status="accepted",
        title="Adolescent eval — syncope",
        message="15F, single syncopal episode at school, hx vasovagal.",
        reasoning="Adolescent medicine workup.",
        outcome="accept",
        responded_seconds_ago=900,
        seconds_ago=960,
    ),

    # --- Resolved ---
    _page(
        doctor_id="dr_lee",
        doctor_name="Dr. Hana Lee",
        specialty=["oncology"],
        room="oncology_unit",
        priority="P3",
        status="resolved",
        title="Chemo reaction — mild",
        message="Grade 1 infusion reaction. Diphenhydramine given, resolved.",
        reasoning="Oncology bedside; reaction management.",
        outcome="resolved",
        responded_seconds_ago=1700,
        seconds_ago=2400,
    ),

    # --- Declined (escalated to backup automatically afterwards) ---
    _page(
        doctor_id="dr_williams",
        doctor_name="Dr. Emily Williams",
        specialty=["surgery", "trauma"],
        room="floor_3_corridor",
        priority="P3",
        status="declined",
        title="Surgical consult — abscess",
        message="Perianal abscess, needs I&D in next 2hr.",
        reasoning="Surgical consult; non-urgent OR booking.",
        outcome="decline",
        responded_seconds_ago=3100,
        seconds_ago=3200,
    ),
]


def main() -> None:
    db = TinyDB(DB_PATH)
    db.drop_tables()
    db.insert_multiple(PAGES)
    print(f"Seeded {len(PAGES)} pages → {DB_PATH}")
    by_status: dict[str, int] = {}
    for p in PAGES:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    for s, n in sorted(by_status.items()):
        print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
