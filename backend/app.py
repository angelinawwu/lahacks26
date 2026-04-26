"""
MedPage Flask backend — hospital paging simulation service.

Run from repo root:
  cd backend && pip install -r requirements.txt
  python app.py

Or from repo root:
  python -m backend.app

Runs on port 8001. The existing FastAPI service stays on port 8000.
"""
from __future__ import annotations

# Eventlet must monkey-patch the stdlib BEFORE anything imports `logging`,
# `threading`, etc. — otherwise their stdlib RLocks stay un-greened and
# eventlet warns "1 RLock(s) were not greened" at boot.
import eventlet  # noqa: E402
eventlet.monkey_patch()

import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# Allow `import state` and `import routes.*` to work whether the script is
# executed from the repo root or from inside backend/.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flask import Flask  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_socketio import SocketIO, join_room, emit  # noqa: E402

import state  # noqa: E402
from routes.doctors import bp as doctors_bp  # noqa: E402
from routes.nurses import bp as nurses_bp  # noqa: E402
from routes.patients import bp as patients_bp  # noqa: E402
from routes.rooms import bp as rooms_bp  # noqa: E402
from routes.pages import bp as pages_bp  # noqa: E402
from routes.queue import bp as queue_bp  # noqa: E402
from routes.proactive import bp as proactive_bp  # noqa: E402
from routes.voice import bp as voice_bp  # noqa: E402
from routes.ehr import bp as ehr_bp  # noqa: E402
from routes.clinician_queue import bp as clinician_queue_bp  # noqa: E402
from routes.paging_modes import bp as paging_modes_bp  # noqa: E402
from routes.settings import bp as settings_bp  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
_log = logging.getLogger("medpage.backend")

# ---------------------------------------------------------------------------
# App + extensions
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "medpage-dev-secret")

CORS(app, origins="*")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    logger=False,
    engineio_logger=False,
)

# Attach socketio to app so blueprints can access it via current_app.socketio
app.socketio = socketio  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
app.register_blueprint(doctors_bp)
app.register_blueprint(nurses_bp)
app.register_blueprint(patients_bp)
app.register_blueprint(rooms_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(queue_bp)
app.register_blueprint(proactive_bp)
app.register_blueprint(voice_bp)
app.register_blueprint(ehr_bp)
app.register_blueprint(clinician_queue_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(paging_modes_bp)

# Seed at import time so Gunicorn workers have data without __main__ running
state.seed()
_log.info(
    "State seeded — doctors=%d nurses=%d patients=%d rooms=%d",
    len(state.DOCTORS), len(state.NURSES), len(state.PATIENTS), len(state.ROOMS),
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "medpage-flask-backend",
        "port": 8001,
        "doctors": len(state.DOCTORS),
        "nurses": len(state.NURSES),
        "patients": len(state.PATIENTS),
        "rooms": len(state.ROOMS),
    }


# ---------------------------------------------------------------------------
# Socket.IO — connection / room management
# ---------------------------------------------------------------------------
@socketio.on("connect")
def on_connect(auth):
    """
    Client auth payload:
      { "role": "operator" }               — joins the operators room
      { "clinician_id": "dr_chen" }        — joins the doctor's personal room
    Both can be combined.
    """
    auth = auth or {}
    role = auth.get("role")
    clinician_id = auth.get("clinician_id")

    if role == "operator":
        join_room("operators")
        _log.info("operator connected")
        emit(
            "snapshot",
            {
                "doctors": list(state.DOCTORS.values()),
                "nurses": list(state.NURSES.values()),
                "patients": list(state.PATIENTS.values()),
                "rooms": list(state.ROOMS.values()),
                "active_pages": [
                    p for p in state.PAGES.values()
                    if p["status"] not in ("cancelled", "expired")
                ],
            },
        )

    if clinician_id:
        join_room(clinician_id)
        _log.info("clinician %s connected", clinician_id)


@socketio.on("disconnect")
def on_disconnect():
    from flask import request as _req
    sid = getattr(_req, "sid", None)
    rooms = []
    if sid:
        try:
            rooms = sorted(
                r for r in socketio.server.manager.get_rooms(sid, "/") or []
                if r != sid
            )
        except Exception:
            rooms = []
    _log.info("client disconnected sid=%s rooms=%s", sid, rooms)


@socketio.on("status_update")
def on_status_update(data):
    """
    Clients can push a status change via Socket.IO instead of REST.
    Payload: { "clinician_id": "dr_chen", "status": "available", "zone": "icu" }
    """
    dr_id = data.get("clinician_id") or data.get("doctor_id")
    new_status = data.get("status")

    if not dr_id or not new_status:
        return

    doc = state.DOCTORS.get(dr_id)
    if doc:
        doc["status"] = new_status
        if "zone" in data:
            doc["zone"] = data["zone"]
        socketio.emit(
            "doctor_status_changed",
            {"id": dr_id, **doc},
            room="operators",
        )
        _log.info("doctor %s status → %s", dr_id, new_status)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    state.seed()
    _log.info(
        "MedPage backend seeded — doctors=%d nurses=%d patients=%d rooms=%d",
        len(state.DOCTORS),
        len(state.NURSES),
        len(state.PATIENTS),
        len(state.ROOMS),
    )
    port = int(os.getenv("BACKEND_PORT", "8001"))
    _log.info("Starting on http://0.0.0.0:%d", port)
    socketio.run(app, host="0.0.0.0", port=port, debug=True, use_reloader=False)
