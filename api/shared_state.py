"""
Unified in-memory + TinyDB state for the merged MedPage backend.

All data lives under db/ (single source of truth). In-memory dicts are
seeded on startup and reset on restart for non-persistent state.

TinyDB-backed (survives restarts):
  CLINICIANS  — db/clinicians.json   (agent dispatch roster, also DOCTORS)
  PAGES       — db/pages.json        (page history + active pages)
  EHR         — db/ehr_records.json  (patient records, keyed by patient_id)

Plain JSON (in-memory, reset on restart):
  ROOMS       — db/rooms.json        (list of room records)

Legacy in-memory dicts kept as empty defaults (NURSES, PATIENTS) so any
stray reference resolves cleanly until those features are removed.
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

_DB_DIR = os.path.join(_REPO_ROOT, "db")


def _load_json(filename: str) -> Any:
    """Load a plain JSON file from db/."""
    path = os.path.join(_DB_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_tinydb_table(filename: str) -> List[Dict]:
    """Load the `_default` table out of a TinyDB-format JSON file (db/...).

    Avoids importing TinyDB just to read; the on-disk format is stable JSON.
    Returns [] if the file is missing or malformed.
    """
    raw = _load_json(filename)
    if not isinstance(raw, dict):
        return []
    table = raw.get("_default") or {}
    return [dict(v) for v in table.values() if isinstance(v, dict)]


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

    # NURSES and PATIENTS are no longer seeded from JSON — the corresponding
    # files were removed during the db/ consolidation. Keep the dicts empty
    # so downstream code that does `state.PATIENTS.get(...)` still works.
    NURSES = {}
    PATIENTS = {}

    # Rooms remain a plain JSON list under db/rooms.json.
    rooms_data = _load_json("rooms.json") or []
    if isinstance(rooms_data, list):
        ROOMS = {r["id"]: dict(r) for r in rooms_data if "id" in r}
    else:
        ROOMS = {}

    # EHR lives in db/ehr_records.json (TinyDB format). Re-key by patient_id
    # so callers can do `state.EHR.get("PT-2024-00412")` directly. Fall back
    # to the TinyDB doc id when patient_id is missing.
    EHR = {}
    for rec in _load_tinydb_table("ehr_records.json"):
        key = rec.get("patient_id") or rec.get("id")
        if key:
            EHR[key] = rec
            # Also synthesize a minimal PATIENTS entry so the patient search
            # endpoint (which iterates PATIENTS first) returns these records.
            PATIENTS[key] = {
                "id": key,
                "name": rec.get("name") or key,
                "room": rec.get("room"),
                "primary_diagnosis": rec.get("primary_diagnosis"),
                "comorbidities": rec.get("comorbidities") or [],
            }

    # Clinicians from TinyDB are the canonical roster — also seed DOCTORS
    # from this same source so identity is consistent across the system.
    CLINICIANS = {c["id"]: dict(c) for c in _get_clinicians_db().all()}
    DOCTORS = {}
    for cid, clin in CLINICIANS.items():
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
