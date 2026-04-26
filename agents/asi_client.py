"""
Thin wrapper around the ASI-1 Mini chat completions endpoint.

Keeps API-key loading + retry/fallback logic in one place so every
agent can just call `asi1_chat(system, user)` and get a string back
(or None if the API is unreachable — the agent then applies its own
fallback policy).
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

ASI1_URL = "https://api.asi1.ai/v1/chat/completions"
ASI1_MODEL = "asi1-mini"
ASI1_API_KEY = os.getenv("ASI1_API_KEY", "")

_log = logging.getLogger("medpage.asi")


def asi1_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    timeout: float = 15.0,
) -> Optional[str]:
    """Call ASI-1 Mini. Returns the assistant text, or None on failure."""
    if not ASI1_API_KEY:
        _log.warning("asi.skip reason=no_api_key")
        return None
    headers = {
        "Authorization": f"Bearer {ASI1_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ASI1_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    sys_len = len(system_prompt or "")
    usr_len = len(user_prompt or "")
    t0 = time.monotonic()
    try:
        r = requests.post(ASI1_URL, headers=headers, json=payload, timeout=timeout)
        elapsed_ms = (time.monotonic() - t0) * 1000
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        _log.info(
            "asi.call model=%s sys=%d usr=%d resp=%d status=%d ms=%.1f",
            ASI1_MODEL, sys_len, usr_len, len(content or ""), r.status_code, elapsed_ms,
        )
        return content
    except requests.Timeout:
        elapsed_ms = (time.monotonic() - t0) * 1000
        _log.error(
            "asi.call TIMEOUT model=%s sys=%d usr=%d ms=%.1f timeout=%.1fs",
            ASI1_MODEL, sys_len, usr_len, elapsed_ms, timeout,
        )
        return None
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - t0) * 1000
        body = ""
        try:
            body = (r.text or "")[:200]  # type: ignore[name-defined]
        except Exception:
            pass
        _log.error(
            "asi.call ERROR model=%s sys=%d usr=%d ms=%.1f err=%r body=%r",
            ASI1_MODEL, sys_len, usr_len, elapsed_ms, str(e)[:200], body,
        )
        return None


def extract_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from an LLM response."""
    if not text:
        return None
    # direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # find first { ... } span
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None
