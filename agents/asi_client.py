"""
LLM chat client for the MedPage agent pipeline.

Priority order:
  1. ASI-1 Mini  — if ASI1_API_KEY is set
  2. Claude      — if ANTHROPIC_API_KEY is set (requires `pip install anthropic`)
  3. None        — agents apply their heuristic fallback

Set exactly one key in .env; both can coexist and ASI-1 is tried first.
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

ASI1_URL      = "https://api.asi1.ai/v1/chat/completions"
ASI1_MODEL    = "asi1-mini"
ASI1_API_KEY  = os.getenv("ASI1_API_KEY", "")

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL       = "claude-haiku-4-5-20251001"   # fast + cheap for structured JSON

_log = logging.getLogger("medpage.asi")


# ---------------------------------------------------------------------------
# ASI-1 Mini
# ---------------------------------------------------------------------------
def _asi1_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: float,
) -> Optional[str]:
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
            {"role": "user",   "content": user_prompt},
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


# ---------------------------------------------------------------------------
# Claude (Anthropic SDK)
# ---------------------------------------------------------------------------
def _claude_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: float,
) -> Optional[str]:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic  # optional dependency
    except ImportError:
        print("[asi1_chat] anthropic package not installed — run: pip install anthropic")
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"[asi1_chat] Claude error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API  (name kept for backward compatibility)
# ---------------------------------------------------------------------------
def asi1_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    timeout: float = 15.0,
) -> Optional[str]:
    """Call ASI-1 Mini, falling back to Claude, then returning None."""
    result = _asi1_chat(system_prompt, user_prompt, temperature, timeout)
    if result is not None:
        return result
    return _claude_chat(system_prompt, user_prompt, temperature, timeout)


def extract_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from an LLM response."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None
