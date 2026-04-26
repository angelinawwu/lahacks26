"""
Unified in-memory + TinyDB state for the merged MedPage backend.

In-memory (seeded from backend/data/*.json, resets on restart):
  DOCTORS, NURSES, PATIENTS, ROOMS, EHR
  PAGING_MODES, CLINICIAN_QUEUE, RECOMMENDATIONS, BRIEFS

TinyDB persistent:
  CLINICIANS  — db/clinicians.json  (agent dispatch roster)
  PAGES       — db/pages.json        (page history + active)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from tinydb import TinyDB, Query

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)

# Add backend/ to sys.path so voice_log and other backend modules resolve.
_BACKEND_DIR = os.path.join(_REPO_ROOT, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_DB_DIR = os.path.join(_REPO_ROOT, "db")


def _load_json(filename: str) -> Any:
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# In-memory state (reset on every restart, seeded from JSON)
# ---------------------------------------------------------------------------
DOCTORS: Dict[str, Dict] = {}
NURSES: Dict[str, Dict] = {}
PATIENTS: Dict[str, Dict] = {}
ROOMS: Dict[str, Dict] = {}
EHR: Dict[str, Dict] = {}

CLINICIAN_QUEUE: Dict[str, Dict] = {}

PAGING_MODES: Dict[str, Any] = {
    "global_mode": "automated",
    "global_set_by": None,
    "global_set_at": None,
    "global_reason": "",
    "zones": {},
    "page_overrides": {},
}

RECOMMENDATIONS: Dict[str, Dict[str, Any]] = {}
BRIEFS: Dict[str, Dict[str, Any]] = {}
SCHEDULED_PAGES: Dict[str, Dict[str, Any]] = {}  # in-memory only; keyed by request_id

# ---------------------------------------------------------------------------
# TinyDB-backed state (survives restarts)
# ---------------------------------------------------------------------------
CLINICIANS: Dict[str, Dict] = {}   # db/clinicians.json
PAGES: Dict[str, Dict] = {}        # db/pages.json

_clinicians_db: Optional[TinyDB] = None
_pages_db: Optional[TinyDB] = None


def _get_clinicians_db() -> TinyDB:
    global _clinicians_db
    if _clinicians_db is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _clinicians_db = TinyDB(os.path.join(_DB_DIR, "clinicians.json"))
    return _clinicians_db


def _get_pages_db() -> TinyDB:
    global _pages_db
    if _pages_db is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _pages_db = TinyDB(os.path.join(_DB_DIR, "pages.json"))
    return _pages_db


# ---------------------------------------------------------------------------
# Page persistence helpers
# ---------------------------------------------------------------------------

def save_page(page: Dict) -> None:
    """Upsert a page into TinyDB and the in-memory dict atomically."""
    db = _get_pages_db()
    Q = Query()
    if db.search(Q.id == page["id"]):
        db.update(page, Q.id == page["id"])
    else:
        db.insert(dict(page))
    PAGES[page["id"]] = page


def load_pages() -> None:
    """Hydrate PAGES from TinyDB on startup."""
    global PAGES
    db = _get_pages_db()
    PAGES = {p["id"]: dict(p) for p in db.all() if "id" in p}


# ---------------------------------------------------------------------------
# Clinician persistence helpers
# ---------------------------------------------------------------------------

def save_clinician(clinician: Dict) -> None:
    """Upsert a clinician record in TinyDB and in-memory dict."""
    db = _get_clinicians_db()
    Q = Query()
    if db.search(Q.id == clinician["id"]):
        db.update(clinician, Q.id == clinician["id"])
    else:
        db.insert(dict(clinician))
    CLINICIANS[clinician["id"]] = clinician


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed() -> None:
    """Load all seed data into module-level dicts. Safe to call multiple times."""
    global DOCTORS, NURSES, PATIENTS, ROOMS, EHR, CLINICIANS

    DOCTORS = {d["id"]: dict(d) for d in _load_json("doctors.json")}
    NURSES = {n["id"]: dict(n) for n in _load_json("nurses.json")}
    PATIENTS = {p["id"]: dict(p) for p in _load_json("patients.json")}
    ROOMS = {r["id"]: dict(r) for r in _load_json("rooms.json")}
    EHR = _load_json("ehr.json")

    # Clinicians from TinyDB (canonical agent dispatch roster)
    CLINICIANS = {c["id"]: dict(c) for c in _get_clinicians_db().all()}

    # Merge TinyDB clinician fields into DOCTORS so the two datasets share one
    # schema. CLINICIANS (db/clinicians.json) is the canonical roster — its
    # identity fields (name, specialty) override DOCTORS to prevent the same
    # id from resolving to two different people across views. Live operational
    # fields (status, zone, on_call, shift times) are also taken from
    # CLINICIANS when present. Runtime stats in DOCTORS (page_count_1hr,
    # active_cases, pager_id, phone) are preserved.
    _CANONICAL_FIELDS = ("name", "specialty", "on_call", "shift_start", "shift_end", "zone", "status")
    for cid, clin in CLINICIANS.items():
        if cid in DOCTORS:
            for field in _CANONICAL_FIELDS:
                if field in clin:
                    DOCTORS[cid][field] = clin[field]
        else:
            # Clinician exists only in TinyDB (not in backend/data/doctors.json).
            # Add a minimal DOCTORS entry so snapshot includes them.
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

    # Pages from TinyDB (persistent history)
    load_pages()

    # Init voice log SQLite DB (lives in backend/)
    try:
        import voice_log  # type: ignore[import]
        voice_log.init_db()
    except Exception:
        pass
