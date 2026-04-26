"""
Sentinel Agent — systemic-risk pattern detector.

Runs on a 30-second interval timer (NOT message-driven). On each tick it:
  1. Pulls clinician statuses + active alerts from TinyDB (and the live
     backend if reachable).
  2. Computes simple statistical signals:
        - alert concentration in one zone
        - unacknowledged page / ack-gap rate
        - specialty coverage holes
        - dangerous caseload concentration on one clinician
  3. Asks ASI-1 Mini to interpret the signals and decide whether they
     amount to a real systemic-risk pattern worth escalating.
  4. If yes, sends a `SentinelInsight` message to the Operator Agent.

The Sentinel never routes or pages anything itself — it only observes and
recommends.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from tinydb import TinyDB
from uagents import Agent, Context

from agents.asi_client import asi1_chat, extract_json
from agents.models import SentinelInsight

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SEED = os.getenv("SENTINEL_SEED", "sentinel-dev-seed")
PORT = int(os.getenv("SENTINEL_PORT", "8004"))
INTERVAL_SECONDS = int(os.getenv("SENTINEL_INTERVAL", "30"))

OPERATOR_ADDRESS = os.getenv("OPERATOR_ADDRESS", "")  # set after first operator boot
DB_PATH = os.getenv("CLINICIAN_DB", "db/clinicians.json")
ALERTS_DB_PATH = os.getenv("ALERTS_DB", "db/alerts.json")

# Backend (optional — preferred when up)
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8001")

agent = Agent(
    name="sentinel",
    seed=SEED,
    port=PORT,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)

# Track previously-emitted insights so we don't spam the operator
_recent_insights: Dict[str, datetime] = {}
INSIGHT_DEDUPE_WINDOW = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def _load_clinicians_local() -> List[Dict[str, Any]]:
    try:
        return TinyDB(DB_PATH).all()
    except Exception:
        return []


def _load_alerts_local() -> List[Dict[str, Any]]:
    try:
        return TinyDB(ALERTS_DB_PATH).all()
    except Exception:
        return []


def _load_clinicians_backend() -> Optional[List[Dict[str, Any]]]:
    """Try to pull live doctor data from backend. Sync, short timeout."""
    try:
        import requests
        r = requests.get(f"{BACKEND_URL}/api/doctors", timeout=1.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _load_pages_backend() -> Optional[List[Dict[str, Any]]]:
    try:
        import requests
        r = requests.get(f"{BACKEND_URL}/api/pages", timeout=1.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pattern signals
# ---------------------------------------------------------------------------
def _signal_alert_concentration(alerts: List[Dict]) -> Optional[Dict]:
    """≥3 alerts in the same zone within the last 10 min."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    by_zone: Counter[str] = Counter()
    for a in alerts:
        ts = a.get("created_at") or a.get("timestamp")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t < cutoff:
            continue
        zone = a.get("zone") or a.get("room") or "unknown"
        by_zone[str(zone)] += 1

    if not by_zone:
        return None
    top_zone, count = by_zone.most_common(1)[0]
    if count >= 3:
        return {"zone": top_zone, "count": count, "window_min": 10}
    return None


def _signal_ack_gap(pages: List[Dict]) -> Optional[Dict]:
    """≥2 pages in 'paging'/'escalated' status older than 60s."""
    now = datetime.now(timezone.utc)
    stale = []
    for p in pages:
        if p.get("status") not in ("paging", "pending", "escalated"):
            continue
        ts = p.get("created_at")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (now - t).total_seconds()
        if age > 60:
            stale.append({"page_id": p.get("id"), "age_seconds": int(age),
                          "doctor_id": p.get("doctor_id"),
                          "priority": p.get("priority")})
    if len(stale) >= 2:
        return {"stale_count": len(stale), "details": stale[:5]}
    return None


def _signal_coverage_hole(clinicians: List[Dict]) -> Optional[Dict]:
    """Any specialty with 0 'available' clinicians."""
    by_specialty_total: Dict[str, int] = defaultdict(int)
    by_specialty_available: Dict[str, int] = defaultdict(int)
    for c in clinicians:
        specialties = c.get("specialty") or c.get("specialties") or []
        if isinstance(specialties, str):
            specialties = [specialties]
        status = c.get("status", "unknown")
        for s in specialties:
            by_specialty_total[s] += 1
            if status == "available":
                by_specialty_available[s] += 1

    holes = [
        s for s, total in by_specialty_total.items()
        if total > 0 and by_specialty_available.get(s, 0) == 0
    ]
    if holes:
        return {"specialties_uncovered": holes,
                "totals": dict(by_specialty_total)}
    return None


def _signal_caseload_concentration(clinicians: List[Dict]) -> Optional[Dict]:
    """Any single clinician with page_count_1hr ≥ 5 OR active_cases ≥ 4."""
    flagged = []
    for c in clinicians:
        pc = c.get("page_count_1hr", 0) or 0
        ac = c.get("active_cases", 0) or 0
        if pc >= 5 or ac >= 4:
            flagged.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "page_count_1hr": pc,
                "active_cases": ac,
                "zone": c.get("zone"),
            })
    if flagged:
        return {"overloaded": flagged}
    return None


# ---------------------------------------------------------------------------
# ASI-1 interpretation
# ---------------------------------------------------------------------------
SENTINEL_SYSTEM_PROMPT = """You are the Sentinel Agent in a hospital paging
system. You watch live signals — alert clusters, unacknowledged pages,
specialty coverage holes, clinician caseload — and decide whether they
constitute a SYSTEMIC RISK pattern that the Operator should pre-empt.

You DO NOT page or route anything. You only flag patterns.

Given a JSON payload of computed signals, respond with a JSON object:
{
  "should_emit": true | false,
  "pattern_type": "alert_concentration" | "ack_gap" | "coverage_hole" | "caseload_concentration" | "off_hours_risk",
  "severity": "info" | "warning" | "critical",
  "summary": "one-sentence plain-language description for the Operator",
  "confidence": 0.0-1.0,
  "reasoning": "two-sentence rationale"
}

Rules:
- Only set should_emit=true when at least one signal is materially abnormal.
- Prefer 'warning' over 'critical'. Reserve 'critical' for: coverage hole +
  active P1/P2, OR ≥3 stale pages, OR clinician with ≥6 pages/hr.
- If multiple signals are present, pick the most severe pattern_type.
- summary must be plain language, no jargon, <140 chars.
"""


def _interpret_signals(signals: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ask ASI-1 to decide if signals add up to a real pattern."""
    user_prompt = json.dumps(signals, default=str)
    raw = asi1_chat(SENTINEL_SYSTEM_PROMPT, user_prompt, temperature=0.1, timeout=10.0)
    parsed = extract_json(raw) if raw else None

    if parsed and isinstance(parsed, dict) and parsed.get("should_emit"):
        return parsed

    # Heuristic fallback: emit if any single signal tripped, conservatively.
    if not raw:
        for key, sev in (
            ("ack_gap", "warning"),
            ("coverage_hole", "critical"),
            ("alert_concentration", "warning"),
            ("caseload_concentration", "warning"),
        ):
            if signals.get(key):
                return {
                    "should_emit": True,
                    "pattern_type": key,
                    "severity": sev,
                    "summary": f"Sentinel heuristic detected {key.replace('_',' ')}.",
                    "confidence": 0.5,
                    "reasoning": "ASI-1 unavailable; deterministic fallback.",
                }
    return None


def _dedupe_key(pattern_type: str, signals: Dict[str, Any]) -> str:
    """Stable key so we don't re-emit the same pattern every 30s."""
    if pattern_type == "alert_concentration":
        z = (signals.get("alert_concentration") or {}).get("zone", "")
        return f"alert_concentration:{z}"
    if pattern_type == "coverage_hole":
        specs = sorted((signals.get("coverage_hole") or {}).get("specialties_uncovered", []))
        return f"coverage_hole:{','.join(specs)}"
    if pattern_type == "caseload_concentration":
        ids = sorted([
            x["id"] for x in (signals.get("caseload_concentration") or {}).get("overloaded", [])
            if x.get("id")
        ])
        return f"caseload_concentration:{','.join(ids)}"
    return pattern_type


def _is_duplicate(key: str) -> bool:
    seen = _recent_insights.get(key)
    if seen and datetime.now() - seen < INSIGHT_DEDUPE_WINDOW:
        return True
    _recent_insights[key] = datetime.now()
    return False


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------
async def _tick(ctx: Context):
    # Prefer backend, fall back to local TinyDB
    clinicians = _load_clinicians_backend() or _load_clinicians_local()
    pages = _load_pages_backend() or []
    alerts = _load_alerts_local()

    signals: Dict[str, Any] = {}
    s = _signal_alert_concentration(alerts)
    if s: signals["alert_concentration"] = s
    s = _signal_ack_gap(pages)
    if s: signals["ack_gap"] = s
    s = _signal_coverage_hole(clinicians)
    if s: signals["coverage_hole"] = s
    s = _signal_caseload_concentration(clinicians)
    if s: signals["caseload_concentration"] = s

    if not signals:
        ctx.logger.debug("[sentinel] tick: all clear")
        return

    ctx.logger.info(f"[sentinel] tick signals: {list(signals.keys())}")

    interp = _interpret_signals(signals)
    if not interp:
        return

    pattern_type = interp.get("pattern_type", "")
    dedupe_key = _dedupe_key(pattern_type, signals)
    if _is_duplicate(dedupe_key):
        ctx.logger.info(f"[sentinel] suppressed duplicate insight: {dedupe_key}")
        return

    affected = signals.get(pattern_type, {}) or {}
    insight = SentinelInsight(
        pattern_type=pattern_type,
        severity=interp.get("severity", "warning"),
        summary=interp.get("summary", "Sentinel detected a systemic risk pattern."),
        affected_zones=[affected["zone"]] if isinstance(affected, dict) and affected.get("zone") else [],
        affected_specialties=affected.get("specialties_uncovered", []) if isinstance(affected, dict) else [],
        affected_clinicians=[
            x.get("id") for x in affected.get("overloaded", [])
            if isinstance(x, dict) and x.get("id")
        ] if isinstance(affected, dict) else [],
        metrics=signals,
        detected_at=datetime.now(timezone.utc).isoformat(),
        confidence=float(interp.get("confidence", 0.6)),
        raw_reasoning=interp.get("reasoning", ""),
    )

    if not OPERATOR_ADDRESS:
        ctx.logger.warning(
            "[sentinel] OPERATOR_ADDRESS not set — printing insight only."
        )
        ctx.logger.info(f"[sentinel] INSIGHT: {insight}")
        return

    await ctx.send(OPERATOR_ADDRESS, insight)
    ctx.logger.info(
        f"[sentinel] sent insight pattern={insight.pattern_type} "
        f"severity={insight.severity} → operator"
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
@agent.on_event("startup")
async def _startup(ctx: Context):
    ctx.logger.info(f"[sentinel] address={agent.address}")
    ctx.logger.info(
        f"[sentinel] interval={INTERVAL_SECONDS}s "
        f"operator_set={'yes' if OPERATOR_ADDRESS else 'NO — set OPERATOR_ADDRESS in .env'}"
    )


@agent.on_interval(period=float(INTERVAL_SECONDS))
async def _interval(ctx: Context):
    try:
        await _tick(ctx)
    except Exception as e:  # noqa: BLE001
        ctx.logger.error(f"[sentinel] tick error: {e}")


if __name__ == "__main__":
    agent.run()
