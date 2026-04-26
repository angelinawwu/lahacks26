"""
Shared in-memory state for the MedPage Flask backend.

All data lives in module-level dicts and is seeded from JSON files on
startup. Pages are runtime-only (not persisted to JSON).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(_REPO_ROOT, "db")
_CLINICIANS_DB_PATH = os.path.join(DB_DIR, "clinicians.json")
_PAGES_DB_PATH = os.path.join(DB_DIR, "pages.json")
_EHR_DB_PATH = os.path.join(DB_DIR, "ehr_records.json")
_ROOMS_PATH = os.path.join(DB_DIR, "rooms.json")


def _load(filename: str) -> Any:
    """Load a plain JSON file from db/."""
    path = os.path.join(DB_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_tinydb_table(path: str) -> List[Dict]:
    """Read the `_default` table out of a TinyDB-format JSON file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    table = raw.get("_default") or {}
    return [dict(v) for v in table.values() if isinstance(v, dict)]


def _load_clinicians_from_db() -> List[Dict]:
    """Canonical clinician roster from db/clinicians.json (TinyDB format)."""
    return [c for c in _load_tinydb_table(_CLINICIANS_DB_PATH) if "id" in c]


def _load_pages_from_db() -> List[Dict]:
    """Seeded pages from db/pages.json so the operator dashboard populates."""
    return [p for p in _load_tinydb_table(_PAGES_DB_PATH) if "id" in p]


def _load_ehr_from_db() -> Dict[str, Dict]:
    """EHR records from db/ehr_records.json, keyed by patient_id."""
    out: Dict[str, Dict] = {}
    for rec in _load_tinydb_table(_EHR_DB_PATH):
        key = rec.get("patient_id") or rec.get("id")
        if key:
            out[key] = rec
    return out


DOCTORS: Dict[str, Dict] = {}
NURSES: Dict[str, Dict] = {}
PATIENTS: Dict[str, Dict] = {}
ROOMS: Dict[str, Dict] = {}
EHR: Dict[str, Dict] = {}
PAGES: Dict[str, Dict] = {}   # runtime only — cleared on restart

# Operator-editable clinician dispatch priority queue.
# Keys are doctor IDs; values are queue entry dicts.
# See routes/clinician_queue.py for the full schema.
CLINICIAN_QUEUE: Dict[str, Dict] = {}

# Paging mode configuration — global + per-zone + per-page overrides.
# See routes/paging_modes.py for the full schema.
PAGING_MODES: Dict[str, Any] = {
    "global_mode": "automated",
    "global_set_by": None,
    "global_set_at": None,
    "global_reason": "",
    "zones": {},
    "page_overrides": {},
}


def seed() -> None:
    """Load all seed data into module-level dicts (db/ as single source)."""
    global DOCTORS, NURSES, PATIENTS, ROOMS, EHR, PAGES

    # NURSES + PATIENTS json sources were removed during db/ consolidation.
    NURSES = {}
    PATIENTS = {}

    rooms_data = _load("rooms.json") or []
    ROOMS = (
        {r["id"]: dict(r) for r in rooms_data if isinstance(r, dict) and "id" in r}
        if isinstance(rooms_data, list) else {}
    )

    EHR = _load_ehr_from_db()
    # Synthesize PATIENTS entries from EHR so any code iterating PATIENTS
    # still discovers our patient roster.
    for pid, rec in EHR.items():
        PATIENTS[pid] = {
            "id": pid,
            "name": rec.get("name") or pid,
            "room": rec.get("room"),
            "primary_diagnosis": rec.get("primary_diagnosis"),
            "comorbidities": rec.get("comorbidities") or [],
        }

    PAGES = {p["id"]: dict(p) for p in _load_pages_from_db()}

    # Clinicians from TinyDB are now the canonical doctor roster.
    DOCTORS = {}
    for clin in _load_clinicians_from_db():
        cid = clin["id"]
        DOCTORS[cid] = {
            "id": cid,
            "name": clin.get("name", cid),
            "specialty": clin.get("specialty", []),
            "status": clin.get("status", "available"),
            "zone": clin.get("zone", ""),
            "on_call": clin.get("on_call", False),
            "page_count_1hr": 0,
            "active_cases": 0,
            **{k: v for k, v in clin.items()
               if k not in ("name", "specialty", "status", "zone", "on_call")},
        }

    try:
        import voice_log
        voice_log.init_db()
    except Exception:
        pass
