"""
Voice Event Log — SQLite-backed store of every voice-channel input.

Each row captures one voice utterance ingested by the backend (either via
audio transcription or a raw on-device transcript). Stored fields make the
event available to downstream agents *without* re-running transcription:

    id              — uuid4 hex of this event
    channel         — voice channel (requested_by, falls back to "unknown")
    source          — "audio" | "transcript"
    transcript      — full transcribed text
    summary         — one-line synthesised description (≤200 chars)
    priority_hint   — P1..P4 from the lightweight parser
    specialty_hint  — cardiology / neurology / ... if matched
    room            — room/zone token if matched
    patient_id      — patient id token if matched
    requested_by    — operator / nurse id who spoke
    endpoint        — which voice route ingested it
    linked_page_id  — set when the event triggered a page (urgent flow)
    created_at      — ISO-8601 UTC timestamp

The database file lives at backend/data/voice_log.sqlite3 by default and is
created on first call. sqlite3 is in the Python stdlib, so no extra deps.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

_log = logging.getLogger("medpage.voice_log")

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "voice_log.sqlite3"
)
DB_PATH = os.getenv("VOICE_LOG_DB", _DEFAULT_PATH)

_lock = threading.Lock()
_initialised = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(path: Optional[str] = None) -> None:
    """Create the table + indexes if missing. Safe to call repeatedly."""
    global DB_PATH, _initialised
    if path:
        DB_PATH = path
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_events (
                id              TEXT PRIMARY KEY,
                channel         TEXT NOT NULL,
                source          TEXT NOT NULL,
                transcript      TEXT NOT NULL,
                summary         TEXT NOT NULL,
                priority_hint   TEXT,
                specialty_hint  TEXT,
                room            TEXT,
                patient_id      TEXT,
                requested_by    TEXT,
                endpoint        TEXT,
                linked_page_id  TEXT,
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_voice_events_channel
                ON voice_events(channel);
            CREATE INDEX IF NOT EXISTS idx_voice_events_created_at
                ON voice_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_voice_events_room
                ON voice_events(room);
            """
        )
    _initialised = True
    _log.info("voice_log ready at %s", DB_PATH)


def _ensure() -> None:
    if not _initialised:
        init_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_summary(transcript: str, parsed: Dict[str, Any]) -> str:
    """
    Synthesise a one-line summary from the transcript + parsed hints.
    Format: "[P1|cardiology|icu|pt_42] <first 140 chars of transcript>"
    Anything missing is omitted from the bracket.
    """
    tags = [
        parsed.get("priority_hint"),
        parsed.get("specialty_hint"),
        parsed.get("room"),
        parsed.get("patient_id"),
    ]
    tag_str = "|".join(t for t in tags if t)
    snippet = " ".join((transcript or "").split())[:140]
    if tag_str:
        return f"[{tag_str}] {snippet}"
    return snippet


def log_event(
    *,
    transcript: str,
    parsed: Dict[str, Any],
    source: str = "transcript",
    requested_by: Optional[str] = None,
    endpoint: Optional[str] = None,
    linked_page_id: Optional[str] = None,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert a voice event and return the stored row as a dict.
    """
    _ensure()
    event_id = uuid4().hex
    channel = requested_by or "unknown"
    summary = summary or build_summary(transcript, parsed)
    row = {
        "id": event_id,
        "channel": channel,
        "source": source,
        "transcript": transcript,
        "summary": summary,
        "priority_hint": parsed.get("priority_hint"),
        "specialty_hint": parsed.get("specialty_hint"),
        "room": parsed.get("room"),
        "patient_id": parsed.get("patient_id"),
        "requested_by": requested_by,
        "endpoint": endpoint,
        "linked_page_id": linked_page_id,
        "created_at": _now(),
    }
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO voice_events (
                id, channel, source, transcript, summary,
                priority_hint, specialty_hint, room, patient_id,
                requested_by, endpoint, linked_page_id, created_at
            ) VALUES (
                :id, :channel, :source, :transcript, :summary,
                :priority_hint, :specialty_hint, :room, :patient_id,
                :requested_by, :endpoint, :linked_page_id, :created_at
            )
            """,
            row,
        )
    return row


def link_page(event_id: str, page_id: str) -> None:
    """Attach a page_id to an existing voice event (urgent flow)."""
    _ensure()
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE voice_events SET linked_page_id = ? WHERE id = ?",
            (page_id, event_id),
        )


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM voice_events WHERE id = ?", (event_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def recent_events(
    limit: int = 50,
    channel: Optional[str] = None,
    room: Optional[str] = None,
    since_minutes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Newest-first list of events with optional filters."""
    _ensure()
    where = []
    params: List[Any] = []
    if channel:
        where.append("channel = ?")
        params.append(channel)
    if room:
        where.append("room = ?")
        params.append(room)
    if since_minutes is not None:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        ).isoformat()
        where.append("created_at >= ?")
        params.append(cutoff)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(int(limit))
    with _connect() as conn:
        cur = conn.execute(
            f"SELECT * FROM voice_events{where_sql} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def list_channels() -> List[Dict[str, Any]]:
    """All distinct channels with event counts and last-seen timestamps."""
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT channel,
                   COUNT(*)        AS event_count,
                   MAX(created_at) AS last_seen
            FROM voice_events
            GROUP BY channel
            ORDER BY last_seen DESC
            """
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def count_since(minutes: int = 10, room: Optional[str] = None) -> int:
    """Count events in the last N minutes — used by sentinel signals."""
    _ensure()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat()
    sql = "SELECT COUNT(*) AS n FROM voice_events WHERE created_at >= ?"
    params: List[Any] = [cutoff]
    if room:
        sql += " AND room = ?"
        params.append(room)
    with _connect() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
    return int(row["n"]) if row else 0
