"""
Gunicorn config for the MedPage Flask backend.

Flask-SocketIO requires exactly 1 worker when using eventlet/gevent.
Multiple workers break shared in-memory state and Socket.IO rooms.

Run:
  gunicorn -c gunicorn.conf.py app:app
"""
import os

worker_class = "eventlet"
workers = 1                        # must stay 1 for Socket.IO + shared state
bind = f"0.0.0.0:{os.getenv('BACKEND_PORT', '8001')}"
loglevel = "info"
accesslog = "-"                    # stdout
errorlog = "-"                     # stdout
timeout = 120
keepalive = 5
