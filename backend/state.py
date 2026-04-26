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
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLINICIANS_DB_PATH = os.path.join(_REPO_ROOT, "db", "clinicians.json")


def _load(filename: str) -> Any:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_clinicians_from_db() -> List[Dict]:
    """Read the canonical clinician roster from TinyDB on disk.

    Avoids importing tinydb here so the Flask backend stays independent of
    the FastAPI service; the file format is stable JSON.
    """
    if not os.path.exists(_CLINICIANS_DB_PATH):
        return []
    try:
        with open(_CLINICIANS_DB_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    table = raw.get("_default") or {}
    return [dict(v) for v in table.values() if isinstance(v, dict) and "id" in v]


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

    # Merge canonical clinician roster from db/clinicians.json. That TinyDB
    # file is the source of truth for who exists; doctors.json only carries
    # operational extras (pager_id, phone, runtime stats). Without this merge
    # the operator snapshot omits any clinician that lives only in TinyDB.
    _CANONICAL_FIELDS = ("name", "specialty", "on_call", "shift_start", "shift_end", "zone", "status")
    for clin in _load_clinicians_from_db():
        cid = clin["id"]
        if cid in DOCTORS:
            for field in _CANONICAL_FIELDS:
                if field in clin:
                    DOCTORS[cid][field] = clin[field]
        else:
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

    import voice_log
    voice_log.init_db()
