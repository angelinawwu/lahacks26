# MedPage (LAHacks 2026)

MedPage is a realtime AI-driven hospital paging system. Clinical alerts are classified by priority, matched to available clinicians using zone proximity and caseload, and dispatched with SBAR briefs — all in seconds.

## Live URLs (EC2: 18.145.218.29)

| Service | URL |
|---------|-----|
| **Operator Dashboard** | http://18.145.218.29/operator |
| **Clinician View** | http://18.145.218.29/clinician?id=dr_chen |
| **FastAPI REST + Socket.IO** | http://18.145.218.29:8000 |
| **FastAPI via nginx** | http://18.145.218.29/fastapi/ |
| **Flask Management API** | http://18.145.218.29/api/ |
| **Socket.IO** (nginx) | http://18.145.218.29/socket.io/ |

### Key API Endpoints

**FastAPI (port 8000 / `/fastapi/`)**
- `POST /dispatch` — submit a clinical alert; runs the full agent pipeline
- `GET /clinicians` — list all clinicians (from TinyDB)
- `GET /active-cases` — current in-memory dispatch state
- `GET /health` — health check

**Flask Management API (`/api/`)**
- `GET /api/doctors` — list doctors with live status
- `GET /api/pages` — all pages (created by agent on dispatch)
- `GET /api/queue` — page queue with priority breakdown
- `GET /api/patients` — patient list
- `GET /api/rooms` — room/floor layout
- `GET /api/ehr/<patient_id>/summary` — patient EHR summary
- `POST /api/page/<id>/respond` — clinician accepts/declines a page
- `GET /api/proactive` — sentinel agent insights
- `POST /api/voice/urgent` — voice-to-page (urgent mode)

## Project Structure

```
api/           FastAPI backend — dispatch endpoint + Socket.IO
backend/       Flask backend — management routes, paging state, SBAR delivery
  routes/      Blueprint modules (doctors, pages, queue, EHR, proactive, voice…)
agents/        AI agent pipeline
  operator_agent.py   Orchestrator — runs the full dispatch pipeline
  priority_handler.py Classifies alerts P1–P4 via ASI-1 Mini
  case_handler.py     Ranks clinicians by specialty, zone, caseload
  sentinel_agent.py   Detects systemic risk patterns (30s intervals)
  skills/brief.py     Generates <100-word SBAR briefs on page accept
  backend_client.py   Async HTTP client for agent → Flask calls
  queue_manager.py    Tracks pages, auto-escalates on timeout
frontend/      Next.js web app (operator dashboard + clinician view)
db/            TinyDB JSON data files (clinicians, EHR, schedules)
config/        Autonomy config (review vs autonomous mode per zone/priority)
deploy/        Systemd service files + install script
```

## Architecture

```
Browser
  │
  ├─ REST  → NEXT_PUBLIC_API_URL (port 8000) → FastAPI
  │              POST /dispatch
  │                └─ process_alert()          ← full agent pipeline
  │                     ├─ priority_handler    classify P1–P4
  │                     ├─ case_handler        rank clinicians (ASI-1 + heuristics)
  │                     └─ backend_client      POST /api/page → Flask
  │                                              └─ Flask Socket.IO → clinician
  │
  └─ Socket.IO → port 8000 → FastAPI Socket.IO
                   alert_created, dispatch_decision, incoming_page,
                   page_resolved, alert_updated, clinician_status_changed

nginx (port 80)
  /api/       → Flask  :8001
  /socket.io/ → Flask  :8001
  /fastapi/   → FastAPI :8000
  /           → Next.js :3000
```

## Quick Start (local dev)

### 1) Install dependencies

```bash
pip install -r requirements.txt
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
```

### 2) Start Flask backend

```bash
cd backend
python app.py        # port 8001
```

### 3) Start FastAPI

```bash
uvicorn api.main:asgi_app --reload --port 8000
```

### 4) Start frontend

```bash
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL and NEXT_PUBLIC_SOCKET_URL
npm run dev                         # port 3000
```

Open http://localhost:3000/operator (operator dashboard) or http://localhost:3000/clinician?id=dr_chen (clinician view).

## Deployment (EC2)

Services are managed by systemd:

```bash
# Restart backend
sudo systemctl restart medpage-backend    # Flask :8001
sudo systemctl restart medpage-fastapi    # FastAPI :8000

# View logs
sudo journalctl -u medpage-backend -f
sudo journalctl -u medpage-fastapi -f

# Full redeploy from scratch
sudo bash deploy/install.sh
```

## App Routes

| Route | Description |
|-------|-------------|
| `/operator` | Operator dashboard — submit alerts, view dispatch decisions, monitor queue |
| `/clinician?id=<doctor_id>` | Clinician view — receive pages, accept/decline, get SBAR brief |

Example clinician IDs: `dr_chen`, `dr_rodriguez`, `dr_park`, `dr_goldberg`, `dr_robinson`

## Agents

| Agent | Port | Role |
|-------|------|------|
| `operator_agent.py` | 8001 (uAgents) | Orchestrator; handles Chat Protocol from ASI:One |
| `priority_handler.py` | 8002 | Classifies alert severity P1–P4 |
| `case_handler.py` | 8003 | Ranks clinicians by specialty/zone/caseload |
| `sentinel_agent.py` | 8004 | Detects systemic risk, sends proactive recommendations |

To run agents as standalone uAgents servers:

```bash
python run_all.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://127.0.0.1:8001` | Flask backend URL (used by agents) |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | FastAPI URL (used by frontend) |
| `NEXT_PUBLIC_SOCKET_URL` | `http://127.0.0.1:8000` | Socket.IO URL (used by frontend) |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins for FastAPI |
| `CLINICIANS_DB` | `db/clinicians.json` | TinyDB path for clinician data |
| `AUTONOMY_CONFIG` | `config/autonomy_config.json` | Zone/priority autonomy policy |
