# Voice Channel Storage — Dataflow

A small SQLite-backed log that captures every voice utterance ingested by
MedPage so that downstream agents (operator, sentinel) have situational
awareness across requests. Lives entirely on the EC2 instance — no
external service, no extra deps (Python stdlib `sqlite3`).

## What is stored

One row per voice event:

| Field            | Description                                                 |
|------------------|-------------------------------------------------------------|
| `id`             | uuid4 hex of the event                                      |
| `channel`        | voice channel id (`requested_by`, falls back to `unknown`)  |
| `source`         | `audio` (Whisper) or `transcript` (on-device)               |
| `transcript`     | full transcribed text                                       |
| `summary`        | one-line synthesis: `[P1\|cardiology\|icu\|pt_42] <text>`   |
| `priority_hint`  | P1..P4 from the lightweight parser                          |
| `specialty_hint` | cardiology / neurology / ... if matched                     |
| `room`           | room/zone token if matched                                  |
| `patient_id`     | patient id token if matched                                 |
| `requested_by`   | operator / nurse id who spoke                               |
| `endpoint`       | `/api/voice/transcribe` or `/api/voice/urgent`              |
| `linked_page_id` | set when the event triggered a page (urgent flow)           |
| `created_at`     | ISO-8601 UTC timestamp                                      |

### Storage

- File: `backend/data/voice_log.sqlite3` (override with `VOICE_LOG_DB`)
- Table: `voice_events`
- Indexes: `channel`, `created_at`, `room`
- WAL journal mode for concurrent reads while writing
- `*.sqlite3*` is gitignored

### Module: `backend/voice_log.py`

Public helpers:

- `init_db()` — idempotent table + index creation; called from `state.seed()`
- `log_event(transcript, parsed, source, requested_by, endpoint, linked_page_id, summary)` — insert + return row
- `link_page(event_id, page_id)` — backfill the linkage
- `get_event(id)` — single lookup
- `recent_events(limit, channel, room, since_minutes)` — newest-first list
- `list_channels()` — distinct channels with counts and last_seen
- `count_since(minutes, room)` — quick count for sentinel signals
- `build_summary(transcript, parsed)` — deterministic one-line summary

## Dataflow

```
                     ┌────────────────────────────────────────────┐
                     │             VOICE INGEST PATH              │
                     └────────────────────────────────────────────┘

  Mobile / nurse station
         │
         │ POST audio_b64 or transcript
         ▼
  ┌─────────────────────────────┐
  │ Flask  /api/voice/transcribe│  (transcribe + parse only)
  │ Flask  /api/voice/urgent    │  (transcribe + parse + dispatch page)
  └──────────────┬──────────────┘
                 │ 1. Whisper / on-device transcript
                 │ 2. _parse_transcript() — priority/specialty/room/patient
                 │ 3. voice_log.log_event(...)  ──────────┐
                 │                                        │
                 │                                        ▼
                 │                          ┌──────────────────────────┐
                 │                          │ backend/data/            │
                 │                          │   voice_log.sqlite3      │
                 │                          │     (voice_events)       │
                 │                          └──────────────────────────┘
                 │
                 │ /api/voice/urgent only:
                 │ 4. _select_doctor() + state.PAGES insert
                 │ 5. Socket.IO emit doctor_paged + incoming_page
                 │ 6. linked_page_id stored on the voice event
                 ▼
            HTTP response ({voice_event_id, summary, ...})


                     ┌────────────────────────────────────────────┐
                     │             AGENT READ PATH                │
                     └────────────────────────────────────────────┘

  ┌─────────────────────┐   GET /api/voice/log?room=&channel=&since_minutes=
  │ agents/             │ ─────────────────────────────────────────────────►
  │  backend_client.py  │   GET /api/voice/log/<id>
  │   .get_recent_      │   GET /api/voice/log/recent
  │    voice_events()   │   GET /api/voice/channels
  │   .get_voice_event  │
  │   .get_voice_       │
  │    channels         │
  └──────────┬──────────┘
             │
   ┌─────────┴──────────────────────────────┐
   ▼                                        ▼
┌──────────────────────────┐   ┌────────────────────────────────┐
│ operator_agent.py         │   │ sentinel_agent.py              │
│ process_alert()  Step 3b: │   │ _tick() pulls last 10 min via  │
│   pulls events for the    │   │   _load_voice_events_backend() │
│   alert's room AND its    │   │ _signal_voice_burst() flags    │
│   requested_by channel,   │   │   ≥3 events in same channel or │
│   threads them into       │   │   room → emits SentinelInsight │
│   DispatchDecision.       │   │   (pattern_type=voice_burst)   │
│   details["voice_context"]│   │   to operator agent.           │
└──────────────────────────┘   └────────────────────────────────┘
             │                                  │
             ▼                                  ▼
   surfaces in operator UI            ProactiveRecommendation
   reasoning + queue manager           on operator dashboard
```

## HTTP surface

All under the existing `voice` blueprint (Flask, port 8001):

| Method | Path                          | Purpose                                       |
|--------|-------------------------------|-----------------------------------------------|
| POST   | `/api/voice/transcribe`       | transcribe + parse + **log**                  |
| POST   | `/api/voice/urgent`           | transcribe + parse + dispatch page + **log**  |
| GET    | `/api/voice/log`              | filter by `channel`, `room`, `since_minutes`, `limit` |
| GET    | `/api/voice/log/recent`       | last `?minutes=10` of activity                |
| GET    | `/api/voice/log/<event_id>`   | single event                                  |
| GET    | `/api/voice/channels`         | distinct channels with event_count + last_seen |

Both `POST` endpoints now return `voice_event_id` and `summary` alongside
the existing fields, so callers can refer back to the stored event.

## Agent awareness — what changed

### Operator (`agents/operator_agent.py`)

- After EHR lookup, `process_alert()` calls
  `backend.get_recent_voice_events(room=alert.room, since_minutes=15)` and
  `backend.get_recent_voice_events(channel=alert.requested_by, since_minutes=15)`.
- The deduped event list is attached to `DispatchDecision.details["voice_context"]`
  as `[{id, channel, summary, created_at}, ...]`, in both the immediate-page
  and the no-candidate code paths.
- Best-effort: a backend timeout / failure leaves `voice_context = []` and
  never blocks dispatch.

### Sentinel (`agents/sentinel_agent.py`)

- Each 30 s tick now also pulls the last 10 minutes of voice events from the
  same backend endpoint.
- New signal `_signal_voice_burst` fires when a single channel **or** room
  has ≥3 voice events in that window.
- Emits a `SentinelInsight` with `pattern_type="voice_burst"`, deduped per
  pattern key like the other signals.
- Heuristic fallback (when ASI-1 is unavailable) treats `voice_burst` as a
  `warning` severity.

### Shared schema (`agents/models.py`)

- `SentinelInsight.pattern_type` doc updated to include `"voice_burst"`.

## Lifecycle

- **Init**: `state.seed()` (called from `backend/app.py` on import + `__main__`)
  invokes `voice_log.init_db()`. The DB file and table are created once and
  reused across worker restarts.
- **Writes**: every `/api/voice/transcribe` and `/api/voice/urgent` call.
- **Reads**: agents via the Flask HTTP surface (no direct file access from
  the agent process — keeps the DB single-writer-friendly).
- **Retention**: unlimited for now. Add a TTL pruner later if the table
  grows unbounded — the `created_at` index makes a delete-by-cutoff cheap.

## Files touched

- `backend/voice_log.py` (new) — SQLite store + helpers
- `backend/state.py` — calls `voice_log.init_db()` from `seed()`
- `backend/routes/voice.py` — logs every event, exposes 4 read endpoints
- `agents/backend_client.py` — `get_recent_voice_events`, `get_voice_event`,
  `get_voice_channels`
- `agents/operator_agent.py` — voice-context lookup in `process_alert()`,
  threads into `DispatchDecision.details`
- `agents/sentinel_agent.py` — `_load_voice_events_backend`, `_signal_voice_burst`
- `agents/models.py` — pattern docstring update
- `.gitignore` — `*.sqlite3*`
