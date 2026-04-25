"""
HTTP API for the MedPage agents so the Next.js frontend can call the same
logic as the uAgent handlers (priority + case pipeline).
"""
from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Run from repo root: uvicorn api.main:app --reload
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.models import AlertMessage, PriorityResponse, CaseResponse
from agents.priority_handler import classify
from agents.case_handler import process_case, DB_PATH
from tinydb import TinyDB

app = FastAPI(title="MedPage API", version="0.1.0")

_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _model_dump(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_model_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _model_dump(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return _model_dump(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):
        return _model_dump(obj.dict())
    return obj


class AlertIn(BaseModel):
    raw_text: str
    room: Optional[str] = None
    specialty_hint: Optional[str] = None
    symptoms: Optional[str] = None
    patient_id: Optional[str] = None
    mode: Optional[str] = None
    requested_by: Optional[str] = None


class DispatchOut(BaseModel):
    priority: dict
    case: dict


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/clinicians")
def list_clinicians() -> list[dict[str, Any]]:
    db = TinyDB(DB_PATH)
    return list(db.all())


@app.post("/dispatch", response_model=DispatchOut)
def dispatch(alert: AlertIn) -> DispatchOut:
    msg = AlertMessage(
        raw_text=alert.raw_text,
        room=alert.room,
        specialty_hint=alert.specialty_hint,
        symptoms=alert.symptoms,
        patient_id=alert.patient_id,
        mode=alert.mode,
        requested_by=alert.requested_by,
    )
    pr: PriorityResponse = classify(msg)
    case: CaseResponse = process_case(msg, pr.priority, pr.guardrail_flags)
    return DispatchOut(
        priority=_model_dump(pr),
        case=_model_dump(case),
    )
