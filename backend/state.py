"""
Shared in-memory state for the MedPage Flask backend.

All data lives in module-level dicts and is seeded from JSON files on
startup. Pages are runtime-only (not persisted to JSON).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load(filename: str) -> Any:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


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
    """Load all JSON seed files into the module-level dicts."""
    global DOCTORS, NURSES, PATIENTS, ROOMS, EHR

    DOCTORS = {d["id"]: dict(d) for d in _load("doctors.json")}
    NURSES = {n["id"]: dict(n) for n in _load("nurses.json")}
    PATIENTS = {p["id"]: dict(p) for p in _load("patients.json")}
    ROOMS = {r["id"]: dict(r) for r in _load("rooms.json")}
    EHR = _load("ehr.json")
