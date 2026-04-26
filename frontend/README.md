# MedPage Frontend

Next.js frontend for MedPage's realtime hospital alert workflow. This app provides:

- Clinician mobile experience (primary default)
- Operator dashboard with floor map and active case feed
- Socket.IO + REST integration with the Flask backend (paging, queue, SBAR briefs, proactive recs)
- REST integration with the FastAPI backend (alert dispatch + clinician roster)

## Routes

- `/` -> redirects to `/clinician` (default experience)
- `/clinician?id=dr_chen` -> clinician view
- `/operator` -> operator dashboard

## Prerequisites

- Node.js 18+ (Node 20 recommended)
- npm (or another package manager)
- Backend running from the repository root

## Backends (required)

The frontend talks to **two** services:

```bash
# Flask — paging state, queue, SBAR briefs, proactive recs, Socket.IO
cd backend && python app.py        # :8001

# FastAPI — alert dispatch + clinician roster
uvicorn api.main:asgi_app --reload --port 8000
```

All realtime events (incoming pages, queue updates, doctor status, SBAR
briefs, proactive recommendations) flow over the **Flask** Socket.IO
connection.

## Environment Setup

In `frontend/`:

```bash
cp .env.local.example .env.local
```

Default values:

```env
# Flask backend (REST /api/* and Socket.IO)
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8001

# FastAPI (POST /dispatch, GET /clinicians, PATCH /clinicians/:id)
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Behind nginx on EC2, point both at the public host:

```env
NEXT_PUBLIC_BACKEND_URL=http://18.145.218.29
NEXT_PUBLIC_API_URL=http://18.145.218.29/fastapi
```

## Run Locally

In `frontend/`:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scripts

- `npm run dev` - Start local dev server
- `npm run build` - Build for production
- `npm run start` - Run production build
- `npm run lint` - Run lint checks

## Troubleshooting

- If realtime updates are missing, verify `NEXT_PUBLIC_BACKEND_URL` (Flask Socket.IO lives there).
- If dispatch or clinician roster fails, verify `NEXT_PUBLIC_API_URL` (FastAPI).
- If route data looks stale, restart both backends and the frontend dev server.
