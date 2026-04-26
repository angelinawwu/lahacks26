"""Shared python-socketio AsyncServer instance.

Imported by both api/main.py and all api/routes/* so they share one
Socket.IO namespace without circular imports.
"""
import socketio

sio: socketio.AsyncServer = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
)
