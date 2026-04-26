"""
High-speed backend API client for MedPage agents.

Uses async httpx for concurrent requests - critical for urgent (P1/P2) scenarios
where every millisecond matters. Implements caching for non-urgent data.
"""
from __future__ import annotations

import os
import time
from typing import Optional, Dict, List, Any
from functools import lru_cache
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

# Backend base URL - configurable for different environments
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8001")

# Timeout configs: urgent = fast, non-urgent = can wait slightly
TIMEOUT_URGENT = httpx.Timeout(2.0, connect=0.5)  # P1/P2: 2s total, 0.5s connect
TIMEOUT_STANDARD = httpx.Timeout(5.0, connect=1.0)  # P3/P4: 5s total

# In-memory cache for non-critical data
_cache: Dict[str, Any] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL_SECONDS = 30  # Cache doctor list for 30s


class BackendClient:
    """Async HTTP client for backend API with priority-based timeouts."""
    
    def __init__(self, base_url: str = BACKEND_URL):
        self.base_url = base_url.rstrip("/")
        # Separate clients for different timeout profiles
        self._urgent_client = httpx.AsyncClient(timeout=TIMEOUT_URGENT)
        self._standard_client = httpx.AsyncClient(timeout=TIMEOUT_STANDARD)
    
    def _client_for_priority(self, priority: Optional[str]) -> httpx.AsyncClient:
        """Select appropriate client based on urgency."""
        if priority in ("P1", "P2"):
            return self._urgent_client
        return self._standard_client
    
    async def close(self):
        """Close all HTTP clients."""
        await self._urgent_client.aclose()
        await self._standard_client.aclose()
    
    # ========================================================================
    # Doctor / Clinician Operations
    # ========================================================================
    
    async def get_all_doctors(self, use_cache: bool = True) -> List[Dict]:
        """Fetch all doctors with optional caching for speed."""
        cache_key = "doctors_all"

        if use_cache and self._is_cache_valid(cache_key):
            return _cache[cache_key]

        resp = await self._standard_client.get(f"{self.base_url}/api/doctors")
        resp.raise_for_status()
        doctors = resp.json()

        if use_cache:
            self._set_cache(cache_key, doctors)
        return doctors
    
    async def get_doctor(self, doctor_id: str, priority: Optional[str] = None) -> Optional[Dict]:
        """Fetch single doctor by ID - fast path for urgent priorities."""
        client = self._client_for_priority(priority)

        try:
            resp = await client.get(f"{self.base_url}/api/doctors/{doctor_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return _cache.get(f"doctor_{doctor_id}")
    
    async def update_doctor_status(
        self, 
        doctor_id: str, 
        status: Optional[str] = None,
        zone: Optional[str] = None,
        on_call: Optional[bool] = None
    ) -> Optional[Dict]:
        """Update doctor status - used after paging."""
        payload = {}
        if status:
            payload["status"] = status
        if zone:
            payload["zone"] = zone
        if on_call is not None:
            payload["on_call"] = on_call
        
        resp = await self._standard_client.patch(
            f"{self.base_url}/api/doctors/{doctor_id}/status",
            json=payload
        )
        resp.raise_for_status()
        self._invalidate_cache("doctors_all")
        return resp.json()
    
    # ========================================================================
    # Room & Patient Operations (with EHR)
    # ========================================================================
    
    async def get_room(self, room_id: str, priority: Optional[str] = None) -> Optional[Dict]:
        """Fetch room with current patient - critical for EHR lookup."""
        client = self._client_for_priority(priority)

        # Handle different room ID formats
        formatted_room = room_id if room_id.startswith("room_") else f"room_{room_id}"

        try:
            resp = await client.get(f"{self.base_url}/api/rooms/{formatted_room}")
            if resp.status_code == 404:
                resp = await client.get(f"{self.base_url}/api/rooms/{room_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return None
    
    async def get_patient_with_ehr(
        self, 
        patient_id: str, 
        priority: Optional[str] = None
    ) -> Optional[Dict]:
        """Fetch patient merged with full EHR (medications, labs, vitals, notes)."""
        client = self._client_for_priority(priority)

        try:
            resp = await client.get(f"{self.base_url}/api/patients/{patient_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return None
    
    async def lookup_ehr_by_room(
        self, 
        room_number: str, 
        priority: Optional[str] = None
    ) -> Optional[Dict]:
        """
        High-level helper: room number → patient + EHR.
        Used by Operator Agent for both sparse and rich modes.
        """
        # Step 1: Get room (fast)
        room = await self.get_room(room_number, priority)
        if not room:
            return None
        
        patient_id = room.get("current_patient_id")
        if not patient_id:
            return None
        
        # Step 2: Get patient with EHR
        patient = await self.get_patient_with_ehr(patient_id, priority)
        return patient
    
    # ========================================================================
    # Paging Operations
    # ========================================================================
    
    async def create_page(
        self,
        doctor_id: str,
        priority: str,
        message: str,
        room: Optional[str] = None,
        patient_id: Optional[str] = None,
        requested_by: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Trigger an actual page to a doctor.
        This is the final dispatch action - always use urgent timeout.
        """
        payload = {
            "doctor_id": doctor_id,
            "priority": priority,
            "message": message,
        }
        if room:
            payload["room"] = room
        if patient_id:
            payload["patient_id"] = patient_id
        if requested_by:
            payload["requested_by"] = requested_by
        
        # Pages are always urgent - use fast client
        try:
            resp = await self._urgent_client.post(
                f"{self.base_url}/api/page",
                json=payload
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            return {"error": "timeout", "status": "failed"}
    
    async def respond_to_page(self, page_id: str, outcome: str) -> Optional[Dict]:
        """Record doctor's response to a page."""
        resp = await self._standard_client.post(
            f"{self.base_url}/api/page/{page_id}/respond",
            json={"outcome": outcome}
        )
        resp.raise_for_status()
        return resp.json()
    
    async def get_active_pages(self) -> List[Dict]:
        """Get all active/pending pages for operator dashboard."""
        resp = await self._standard_client.get(f"{self.base_url}/api/pages")
        resp.raise_for_status()
        pages = resp.json()
        return [p for p in pages if p.get("status") in ("paging", "pending")]

    # ========================================================================
    # Voice Event Log — situational awareness for downstream agents
    # ========================================================================

    async def get_recent_voice_events(
        self,
        limit: int = 20,
        channel: Optional[str] = None,
        room: Optional[str] = None,
        since_minutes: Optional[int] = None,
    ) -> List[Dict]:
        """
        Pull recent voice events (newest first). Powered by the SQLite voice
        log on the backend. Use to give agents context about what was just
        spoken on a given channel/room.
        """
        params: Dict[str, Any] = {"limit": limit}
        if channel:
            params["channel"] = channel
        if room:
            params["room"] = room
        if since_minutes is not None:
            params["since_minutes"] = since_minutes
        try:
            resp = await self._standard_client.get(
                f"{self.base_url}/api/voice/log", params=params
            )
            resp.raise_for_status()
            return resp.json().get("events", [])
        except (httpx.TimeoutException, httpx.HTTPError):
            return []

    async def get_voice_event(self, event_id: str) -> Optional[Dict]:
        """Fetch a single voice event by id (e.g. the one that caused a page)."""
        try:
            resp = await self._standard_client.get(
                f"{self.base_url}/api/voice/log/{event_id}"
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.HTTPError):
            return None

    async def get_voice_channels(self) -> List[Dict]:
        """List voice channels with counts and last-seen timestamps."""
        try:
            resp = await self._standard_client.get(
                f"{self.base_url}/api/voice/channels"
            )
            resp.raise_for_status()
            return resp.json().get("channels", [])
        except (httpx.TimeoutException, httpx.HTTPError):
            return []
    
    # ========================================================================
    # Cache Management
    # ========================================================================
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still fresh."""
        if key not in _cache_timestamps:
            return False
        age = time.time() - _cache_timestamps[key]
        return age < CACHE_TTL_SECONDS
    
    def _set_cache(self, key: str, value: Any):
        """Store data in cache."""
        _cache[key] = value
        _cache_timestamps[key] = time.time()
    
    def _invalidate_cache(self, key_prefix: str):
        """Invalidate cache entries matching prefix."""
        keys_to_remove = [k for k in _cache if k.startswith(key_prefix)]
        for k in keys_to_remove:
            del _cache[k]
            del _cache_timestamps[k]
    
    def clear_cache(self):
        """Clear all cached data."""
        _cache.clear()
        _cache_timestamps.clear()


# Singleton instance for convenience
_backend_client: Optional[BackendClient] = None


def get_backend_client() -> BackendClient:
    """Get or create singleton backend client."""
    global _backend_client
    if _backend_client is None:
        _backend_client = BackendClient()
    return _backend_client


async def close_backend_client():
    """Close singleton client on shutdown."""
    global _backend_client
    if _backend_client:
        await _backend_client.close()
        _backend_client = None
