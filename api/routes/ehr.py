"""
EHR query routes.
Replaces backend/routes/ehr.py.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from api import shared_state as state

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _patient_meta(patient_id: str) -> Dict[str, Any]:
    patient = dict(state.PATIENTS.get(patient_id, {}))
    ehr = dict(state.EHR.get(patient_id, {}))
    return {"patient_id": patient_id, **patient, "ehr": ehr}


def _compute_urgency_signals(ehr: Dict[str, Any]) -> List[str]:
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


def _ehr_summary(patient_id: str) -> Dict[str, Any]:
    patient = state.PATIENTS.get(patient_id, {})
    ehr = state.EHR.get(patient_id, {})

    vitals_history = ehr.get("vitals_history", [])
    latest_vitals = vitals_history[-1] if vitals_history else None

    labs = ehr.get("labs", [])
    critical_labs = [
        lab for lab in labs
        if lab.get("flag", "").upper() in ("CRITICAL HIGH", "CRITICAL LOW", "ABNORMAL")
    ]

    medications = ehr.get("medications", [])[:5]
    diagnoses = ehr.get("diagnoses", [])
    notes = ehr.get("notes", [])
    latest_note = notes[-1] if notes else None

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


def _text_search_ehr(query: str) -> List[Dict[str, Any]]:
    tokens = set(re.findall(r"\w+", query.lower()))
    results: List[Dict[str, Any]] = []
    for patient_id in state.EHR:
        ehr = state.EHR[patient_id]
        patient = state.PATIENTS.get(patient_id, {})
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
            results.append({
                "patient_id": patient_id,
                "name": patient.get("name"),
                "room": patient.get("room"),
                "matched_terms": sorted(matched),
                "relevance_score": len(matched),
                "summary": _ehr_summary(patient_id),
            })
    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return results


@router.get("/api/ehr")
def list_ehr():
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
    return {"patients": index, "total": len(index)}


@router.get("/api/ehr/room/{room_id}")
def get_ehr_by_room(room_id: str):
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
    return {"room": room_id, "patients": matches, "total": len(matches), "retrieved_at": _now()}


@router.get("/api/ehr/{patient_id}/summary")
def get_ehr_summary(patient_id: str):
    if patient_id not in state.EHR and patient_id not in state.PATIENTS:
        raise HTTPException(status_code=404, detail=f"patient {patient_id} not found")
    return _ehr_summary(patient_id)


@router.get("/api/ehr/{patient_id}")
def get_ehr(patient_id: str):
    if patient_id not in state.EHR:
        raise HTTPException(status_code=404, detail=f"patient EHR {patient_id} not found")
    patient = state.PATIENTS.get(patient_id, {})
    return {
        "patient_id": patient_id,
        "demographics": patient,
        "ehr": state.EHR[patient_id],
        "retrieved_at": _now(),
    }


@router.post("/api/ehr/query")
async def query_ehr(request: Request):
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    room_filter = body.get("room")
    max_results = int(body.get("max_results", 10))

    results = _text_search_ehr(query)
    if room_filter:
        results = [r for r in results if (r.get("room") or "").lower() == room_filter.lower()]
    results = results[:max_results]

    return {
        "query": query,
        "room_filter": room_filter,
        "total_matches": len(results),
        "results": results,
        "queried_at": _now(),
    }
