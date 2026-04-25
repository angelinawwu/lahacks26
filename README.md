# MedPage (LAHacks 2026)

MedPage is a realtime hospital paging prototype with:

- `api/` - FastAPI backend (REST + Socket.IO via ASGI)
- `frontend/` - Next.js web app (clinician and operator views)
- `db/` - local data artifacts
- `agents/` - agent-related project files

## Project Structure

- `api/` - backend service and realtime events
- `frontend/` - UI and client-side integration
- `requirements.txt` - Python dependencies for backend

## Quick Start

## 1) Start backend

From the repository root:

```bash
pip install -r requirements.txt
uvicorn api.main:asgi_app --reload --port 8000
```

## 2) Start frontend

In a second terminal:

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## App Routes

- `/` -> redirects to `/clinician` (default)
- `/clinician?id=dr_chen` -> clinician view
- `/operator` -> operator dashboard

## Documentation

- Frontend setup and scripts: `frontend/README.md`

