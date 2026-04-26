"""
General hospital settings — backed by config/autonomy_config.json.

Persists:
  - auto_dispatch_rules.max_pages_per_hour       (rate limit)
  - default_operator_view                        ("map" | "feed")

Manual paging mode lives in /api/paging-modes (already implemented),
but for convenience this endpoint also returns the current global
paging mode so the /settings UI can render in a single round-trip.

Endpoints:
  GET  /api/settings   → flat settings + paging-mode echo
  PUT  /api/settings   → update one or more fields
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify, request

import state

bp = Blueprint("settings", __name__)
_log = logging.getLogger("medpage.settings")

CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "autonomy_config.json")
)

VALID_VIEWS = ("map", "feed")


def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def _flatten(cfg: Dict[str, Any]) -> Dict[str, Any]:
    rules = cfg.get("auto_dispatch_rules", {}) or {}
    paging_modes = getattr(state, "PAGING_MODES", {}) or {}
    return {
        "max_pages_per_hour": rules.get("max_pages_per_hour", 3),
        "require_on_call": rules.get("require_on_call", True),
        "allow_off_shift": rules.get("allow_off_shift", False),
        "default_operator_view": cfg.get("default_operator_view", "map"),
        "global_mode": paging_modes.get("global_mode", "automated"),
    }


@bp.get("/api/settings")
def get_settings():
    cfg = _load_config()
    return jsonify(_flatten(cfg))


@bp.put("/api/settings")
def update_settings():
    body = request.get_json(silent=True) or {}
    cfg = _load_config()
    rules = cfg.setdefault("auto_dispatch_rules", {})

    if "max_pages_per_hour" in body:
        try:
            rules["max_pages_per_hour"] = max(1, int(body["max_pages_per_hour"]))
        except (TypeError, ValueError):
            return jsonify({"error": "max_pages_per_hour must be an integer"}), 400

    if "require_on_call" in body:
        rules["require_on_call"] = bool(body["require_on_call"])

    if "allow_off_shift" in body:
        rules["allow_off_shift"] = bool(body["allow_off_shift"])

    if "default_operator_view" in body:
        view = body["default_operator_view"]
        if view not in VALID_VIEWS:
            return jsonify({"error": f"default_operator_view must be one of {VALID_VIEWS}"}), 400
        cfg["default_operator_view"] = view

    _save_config(cfg)
    flat = _flatten(cfg)

    try:
        current_app.socketio.emit("settings_updated", flat, room="operators")
    except Exception as exc:
        _log.warning("settings_updated emit failed: %s", exc)

    _log.info("Settings updated: %s", {k: v for k, v in body.items()})
    return jsonify(flat)
