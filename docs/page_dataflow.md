# Page Lifecycle — Dataflow

End-to-end flow of a page from creation through resolution. Lives entirely
in the Flask backend (`backend/app.py`, port 8001) plus the Next.js
frontend's operator and clinician views.

## States

A page record (in `state.PAGES`) cycles through these `status` values:

| Status      | Set by                              | Meaning                                 |
|-------------|-------------------------------------|-----------------------------------------|
| `paging`    | `POST /api/page` (create)           | Sent to clinician, awaiting response    |
| `accepted`  | `POST /api/page/<id>/respond`       | Clinician accepted; brief in flight     |
| `declined`  | `POST /api/page/<id>/respond`       | Clinician declined                      |
| `escalated` | queue escalation worker             | Reassigned to backup doctor             |
| `cancelled` | `POST /api/queue/<id>/cancel`       | Operator cancelled before response      |
| `resolved`  | `POST /api/page/<id>/resolve`       | Clinician finished the case             |

Doctor `status` mirrors the page lifecycle for the assigned doctor:

| Trigger                         | Doctor status flips to |
|---------------------------------|------------------------|
| Page created → assigned         | `paging` (operator UI) |
| Page accepted                   | `on_case`              |
| Page resolved                   | `available`            |

## Dataflow

```
                     ┌────────────────────────────────────────────┐
                     │                  CREATE                    │
                     └────────────────────────────────────────────┘

  Operator / nurse / voice ingest
         │
         │ POST /api/page  { doctor_id, message, priority, ... }
         ▼
  ┌──────────────────────────────┐
  │ routes/pages.py              │
  │   create_page()              │
  │   • state.PAGES[id] = {...}  │
  │   • doctor.page_count_1hr++  │
  │   • emit doctor_paged   → operators                          │
  │   • emit incoming_page  → <doctor_id>                        │
  └──────────────────────────────┘
                                                                  │
                                                                  ▼
                                                         clinician device
                                                         (ClinicianView)


                     ┌────────────────────────────────────────────┐
                     │                  RESPOND                   │
                     └────────────────────────────────────────────┘

  Clinician taps Accept / Decline
         │
         │ POST /api/page/<id>/respond  { outcome }
         ▼
  ┌──────────────────────────────┐
  │ routes/pages.py              │
  │   respond_to_page()          │
  │   • page.status   = accepted | declined                       │
  │   • page.outcome  = accept   | decline                        │
  │   • page.responded_at = now                                   │
  │   • emit page_response → operators                            │
  │                                                               │
  │   if accept:                                                  │
  │     • doctor.status = "on_case"                               │
  │     • emit doctor_status_changed → operators                  │
  │     • spawn _generate_and_deliver_brief() (background task)   │
  │         → emits sbar_brief → <doctor_id> + operators          │
  └──────────────────────────────┘


                     ┌────────────────────────────────────────────┐
                     │                  RESOLVE                   │
                     └────────────────────────────────────────────┘

  Clinician taps "Resolve page" link on the SBAR card
         │
         │ POST /api/page/<id>/resolve
         ▼
  ┌──────────────────────────────┐
  │ routes/pages.py              │
  │   resolve_page()             │
  │   • page.status   = "resolved"                                │
  │   • page.outcome  = "resolved"                                │
  │   • page.resolved_at = now                                    │
  │   • doctor.status = "available"                               │
  │   • doctor.active_cases = max(0, n-1)                         │
  │   • emit page_response          → operators                   │
  │   • emit doctor_status_changed  → operators                   │
  │   • emit page_resolved          → <doctor_id>                 │
  └──────────────────────────────┘
                                  │
                                  ▼
                       Operator dashboard:
                         • alert moves to "resolved" via pageToAlert()
                         • doctor pin flips back to "available"
                         • queue panel removes the page
```

## Frontend wiring

### Clinician (`frontend/src/app/clinician/ClinicianView.tsx`)

- **Accept** → `respondToPage(pageId, "accept")`; local `status` flips to
  `on_case`; awaits the SBAR brief over the `sbar_brief` socket event.
- **Resolve** → SBAR card's "Resolve page" link calls `resolveCurrent()`,
  which:
  1. fires `resolvePage(pageId)` (best-effort),
  2. marks the recent-pages row as `resolved`,
  3. clears the brief,
  4. flips local `status` to `available`.

### Operator (`frontend/src/app/operator/page.tsx`)

- `pageToAlert()` maps backend `status="resolved"` → alert `status="resolved"`.
- `onPageResponse` handler removes the page from the queue panel for
  `accepted | declined | resolved`.
- `onDoctorChanged` handler picks up the doctor flipping back to
  `available` via the `doctor_status_changed` event.

## HTTP surface (page lifecycle)

| Method | Path                              | Purpose                                       |
|--------|-----------------------------------|-----------------------------------------------|
| POST   | `/api/page`                       | Create + dispatch a page                      |
| POST   | `/api/page/<id>/respond`          | Clinician accept / decline                    |
| POST   | `/api/page/<id>/resolve`          | Clinician marks the case complete             |
| GET    | `/api/pages` / `/api/pages/<id>`  | Read pages (history + active)                 |
| POST   | `/api/queue/<id>/escalate`        | Reassign to backup                            |
| POST   | `/api/queue/<id>/cancel`          | Operator cancels                              |

## Socket.IO events

Emitted by the backend, consumed by the clients:

| Event                     | Room          | Trigger                                   |
|---------------------------|---------------|-------------------------------------------|
| `doctor_paged`            | `operators`   | New page created                          |
| `incoming_page`           | `<doctor_id>` | New page created                          |
| `page_response`           | `operators`   | Page response or resolution               |
| `doctor_status_changed`   | `operators`   | Doctor status flips (accept / resolve)    |
| `sbar_brief`              | `<doctor_id>`, `operators` | Brief generated after accept |
| `page_resolved`           | `<doctor_id>` | Page resolved (lightweight payload)       |

## Files touched

- `backend/routes/pages.py` — added `resolve_page()`, doctor status flip on accept
- `frontend/src/lib/backendApi.ts` — `resolvePage()` helper
- `frontend/src/lib/backendTypes.ts` — `QueueStatus` includes `"resolved"`
- `frontend/src/components/sbar/SbarCard.tsx` — `onResolve` link
- `frontend/src/app/clinician/ClinicianView.tsx` — wire `resolveCurrent`,
  flip local status on accept/resolve
- `frontend/src/app/operator/page.tsx` — map `"resolved"` page status,
  drop resolved pages from queue
