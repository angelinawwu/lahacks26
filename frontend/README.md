# MedPage Frontend

Next.js frontend for MedPage's realtime hospital alert workflow. This app provides:

- Clinician mobile experience (primary default)
- Operator dashboard with floor map and active case feed
- Shared Socket.IO + REST integration with the FastAPI backend

## Routes

- `/` -> redirects to `/clinician` (default experience)
- `/clinician?id=dr_chen` -> clinician view
- `/operator` -> operator dashboard

## Prerequisites

- Node.js 18+ (Node 20 recommended)
- npm (or another package manager)
- Backend running from the repository root

## Backend (required)

From the repository root:

```bash
uvicorn api.main:asgi_app --reload --port 8000
```

The frontend expects REST and Socket.IO on the same base URL.

## Environment Setup

In `frontend/`:

```bash
cp .env.local.example .env.local
```

Default values:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SOCKET_URL=http://127.0.0.1:8000
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

- If realtime updates are missing, verify `NEXT_PUBLIC_SOCKET_URL`.
- If API calls fail, verify `NEXT_PUBLIC_API_URL`.
- If route data looks stale, restart both backend and frontend dev servers.
