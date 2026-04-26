"""
EHR query routes for non-urgent case review.

For non-urgent situations clinical staff query the EHR before deciding
whether to page.  These endpoints expose the EHR data already seeded in
state.EHR and support both exact lookups and a lightweight keyword search
so the operator dashboard / mobile app can surface relevant context.

Endpoints:
  GET  /api/ehr                          — list all patient IDs + summary
  GET  /api/ehr/<patient_id>             — full EHR record
  GET  /api/ehr/<patient_id>/summary     — condensed clinical snapshot
  POST /api/ehr/query                    — keyword / natural-language query
  GET  /api/ehr/room/<room_id>           — EHR records for patients in a room
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
import state

bp = Blueprint("ehr", __name__)
_log = logging.getLogger("medpage.ehr")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _patient_meta(patient_id: str) -> Dict[str, Any]:
    """Return patient demographic record merged with the EHR entry."""
    patient = dict(state.PATIENTS.get(patient_id, {}))
    ehr = dict(state.EHR.get(patient_id, {}))
    return {"patient_id": patient_id, **patient, "ehr": ehr}


def _ehr_summary(patient_id: str) -> Dict[str, Any]:
    """
    Build a concise clinical snapshot of a patient from EHR + demographics.
    Designed for quick clinician review before deciding to page.
    """
    patient = state.PATIENTS.get(patient_id, {})
    ehr = state.EHR.get(patient_id, {})

    # Latest vitals
    vitals_history = ehr.get("vitals_history", [])
    latest_vitals = vitals_history[-1] if vitals_history else None

    # Critical labs
    labs = ehr.get("labs", [])
    critical_labs = [
        lab for lab in labs
        if lab.get("flag", "").upper() in ("CRITICAL HIGH", "CRITICAL LOW", "ABNORMAL")
    ]

    # Active medications (first 5)
    medications = ehr.get("medications", [])[:5]

    # Diagnoses (primary first)
    diagnoses = ehr.get("diagnoses", [])

    # Most recent note
    notes = ehr.get("notes", [])
    latest_note = notes[-1] if notes else None

    # Assigned doctors from patient record
    assigned_doctors = []
    for doc_id, doc in state.DOCTORS.items():
        doc_cases = [
            p for p in state.PAGES.values()
            if p.get("patient_id") == patient_id and p.get("doctor_id") == doc_id
        ]
        if doc_cases:
            assigned_doctors.append({
                "id": doc_id,
                "name": doc.get("name"),
                "specialty": doc.get("specialty"),
                "status": doc.get("status"),
            })

    # Active pages for this patient
    active_pages = [
        {
            "page_id": p.get("id"),
            "priority": p.get("priority"),
            "status": p.get("status"),
            "created_at": p.get("created_at"),
        }
        for p in state.PAGES.values()
        if p.get("patient_id") == patient_id
        and p.get("status") in ("paging", "pending", "escalated")
    ]

    return {
        "patient_id": patient_id,
        "name": patient.get("name"),
        "age": patient.get("age"),
        "room": patient.get("room"),
        "primary_diagnosis": diagnoses[0] if diagnoses else None,
        "all_diagnoses": diagnoses,
        "latest_vitals": latest_vitals,
        "critical_labs": critical_labs,
        "recent_labs": labs[-3:] if labs else [],
        "medications": medications,
        "allergies": ehr.get("allergies", []),
        "latest_note": latest_note,
        "assigned_doctors": assigned_doctors,
        "active_pages": active_pages,
        "urgency_signals": _compute_urgency_signals(ehr),
        "generated_at": _now(),
    }


def _compute_urgency_signals(ehr: Dict[str, Any]) -> List[str]:
    """
    Derive plain-English urgency signals from vitals and labs.
    Used to help operator decide whether a non-urgent case warrants a page.
    """
    signals: List[str] = []
    vitals_history = ehr.get("vitals_history", [])
    if vitals_history:
        v = vitals_history[-1]
        hr = v.get("hr", 0)
        spo2 = v.get("spo2", 100)
        bp_str = v.get("bp", "120/80")
        try:
            systolic = int(bp_str.split("/")[0])
        except Exception:
            systolic = 120

        if hr > 110:
            signals.append(f"Tachycardia (HR {hr})")
        if hr < 50:
            signals.append(f"Bradycardia (HR {hr})")
        if spo2 < 92:
            signals.append(f"Low SpO2 ({spo2}%)")
        if systolic < 90:
            signals.append(f"Hypotension (SBP {systolic})")
        if systolic > 180:
            signals.append(f"Hypertensive urgency (SBP {systolic})")

    for lab in ehr.get("labs", []):
        flag = lab.get("flag", "").upper()
        if flag in ("CRITICAL HIGH", "CRITICAL LOW"):
            signals.append(f"Critical lab: {lab.get('name')} = {lab.get('value')}")

    return signals


def _text_search_ehr(query: str) -> List[Dict[str, Any]]:
    """
    Simple keyword search across EHR notes, diagnoses, medications, and
    patient demographics.  Returns a ranked list of matching records.
    """
    tokens = set(re.findall(r"\w+", query.lower()))
    results: List[Dict[str, Any]] = []

    for patient_id in state.EHR:
        ehr = state.EHR[patient_id]
        patient = state.PATIENTS.get(patient_id, {})

        # Build a searchable blob
        blob_parts: List[str] = [
            patient.get("name", ""),
            patient.get("room", ""),
            patient.get("condition", ""),
        ]
        for d in ehr.get("diagnoses", []):
            blob_parts.append(d.get("description", ""))
        for m in ehr.get("medications", []):
            blob_parts.append(m.get("name", ""))
        for n in ehr.get("notes", []):
            blob_parts.append(n.get("text", ""))
        for allergy in ehr.get("allergies", []):
            blob_parts.append(allergy)

        blob = " ".join(blob_parts).lower()
        blob_tokens = set(re.findall(r"\w+", blob))

        matched = tokens & blob_tokens
        if matched:
            score = len(matched)
            summary = _ehr_summary(patient_id)
            results.append({
                "patient_id": patient_id,
                "name": patient.get("name"),
                "room": patient.get("room"),
                "matched_terms": sorted(matched),
                "relevance_score": score,
                "summary": summary,
            })

    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/api/ehr")
def list_ehr():
    """
    Return a condensed index of all patients with EHR records.
    Useful for operator dashboard: shows who has active flags.
    """
    index = []
    for patient_id in state.EHR:
        patient = state.PATIENTS.get(patient_id, {})
        ehr = state.EHR[patient_id]
        diagnoses = ehr.get("diagnoses", [])
        index.append({
            "patient_id": patient_id,
            "name": patient.get("name"),
            "room": patient.get("room"),
            "primary_diagnosis": diagnoses[0].get("description") if diagnoses else None,
            "has_critical_labs": any(
                lab.get("flag", "").upper() in ("CRITICAL HIGH", "CRITICAL LOW")
                for lab in ehr.get("labs", [])
            ),
            "urgency_signals": _compute_urgency_signals(ehr),
        })
    return jsonify({"patients": index, "total": len(index)})


@bp.get("/api/ehr/<patient_id>")
def get_ehr(patient_id: str):
    """Full EHR record for a patient."""
    if patient_id not in state.EHR:
        return jsonify({"error": "patient EHR not found", "patient_id": patient_id}), 404
    patient = state.PATIENTS.get(patient_id, {})
    ehr = state.EHR[patient_id]
    return jsonify({
        "patient_id": patient_id,
        "demographics": patient,
        "ehr": ehr,
        "retrieved_at": _now(),
    })


@bp.get("/api/ehr/<patient_id>/summary")
def get_ehr_summary(patient_id: str):
    """
    Condensed clinical snapshot for non-urgent case review.
    Returns latest vitals, critical labs, active medications, urgency signals,
    and any currently active pages for this patient.
    """
    if patient_id not in state.EHR and patient_id not in state.PATIENTS:
        return jsonify({"error": "patient not found", "patient_id": patient_id}), 404
    return jsonify(_ehr_summary(patient_id))


@bp.post("/api/ehr/query")
def query_ehr():
    """
    Keyword / natural-language query across all EHR records.
    Intended for non-urgent situations where clinical staff want context
    before deciding to page.

    Body (JSON):
      query       : free-text search string (required)
      room        : filter to a specific room (optional)
      max_results : cap results (default 10)

    Response: ranked list of matching patient summaries.
    """
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    room_filter = body.get("room")
    max_results = int(body.get("max_results", 10))

    results = _text_search_ehr(query)

    if room_filter:
        results = [
            r for r in results
            if (r.get("room") or "").lower() == room_filter.lower()
        ]

    results = results[:max_results]

    return jsonify({
        "query": query,
        "room_filter": room_filter,
        "total_matches": len(results),
        "results": results,
        "queried_at": _now(),
    })


@bp.get("/api/ehr/room/<room_id>")
def get_ehr_by_room(room_id: str):
    """
    Return EHR summaries for all patients currently in a specific room.
    Useful for rounding or when a nurse calls about a room without a patient ID.
    """
    matches = []
    for patient_id, patient in state.PATIENTS.items():
        if patient.get("room", "").lower() == room_id.lower():
            if patient_id in state.EHR:
                matches.append(_ehr_summary(patient_id))
            else:
                matches.append({
                    "patient_id": patient_id,
                    "name": patient.get("name"),
                    "room": patient.get("room"),
                    "ehr": None,
                })

    return jsonify({
        "room": room_id,
        "patients": matches,
        "total": len(matches),
        "retrieved_at": _now(),
    })
