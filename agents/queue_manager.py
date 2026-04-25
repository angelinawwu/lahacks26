"""
Queue Manager for MedPage - Handles pending pages, timeouts, and escalation.

This module manages the queue of pages that are waiting for clinician responses.
When a clinician doesn't respond within the timeout, it automatically escalates
to the next available doctor in the priority list.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from agents.backend_client import get_backend_client
from agents.models import DispatchDecision, CandidateClinician


class PageStatus(str, Enum):
    """Status of a page in the queue."""
    PENDING = "pending"           # Waiting for first doctor to respond
    ESCALATED = "escalated"     # Escalated to next doctor
    ACCEPTED = "accepted"       # Doctor accepted
    DECLINED = "declined"       # Doctor declined
    EXPIRED = "expired"         # All doctors timed out
    CANCELLED = "cancelled"     # Operator cancelled


@dataclass
class QueuedPage:
    """A page in the queue waiting for response or escalation."""
    id: str
    original_decision: DispatchDecision
    priority: str
    current_doctor_index: int = 0
    doctors_list: List[CandidateClinician] = field(default_factory=list)
    status: PageStatus = PageStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    last_sent_at: Optional[datetime] = None
    response_deadline: Optional[datetime] = None
    history: List[Dict] = field(default_factory=list)
    page_result: Optional[Dict] = None
    
    @property
    def current_doctor(self) -> Optional[CandidateClinician]:
        """Get the current doctor being paged."""
        if 0 <= self.current_doctor_index < len(self.doctors_list):
            return self.doctors_list[self.current_doctor_index]
        return None
    
    @property
    def is_timed_out(self) -> bool:
        """Check if current page has timed out."""
        if not self.response_deadline:
            return False
        return datetime.now() > self.response_deadline
    
    @property
    def has_more_doctors(self) -> bool:
        """Check if there are more doctors to escalate to."""
        return self.current_doctor_index < len(self.doctors_list) - 1
    
    @property
    def wait_time_seconds(self) -> int:
        """Get seconds since last page sent."""
        if not self.last_sent_at:
            return 0
        return int((datetime.now() - self.last_sent_at).total_seconds())


class PageQueueManager:
    """
    Manages the queue of pending pages with automatic escalation.
    
    Features:
    - Tracks pending pages with timeouts
    - Auto-escalates to next doctor on timeout
    - Provides queue visualization data
    - Allows operator intervention (cancel, manual escalate)
    """
    
    # Timeout configuration by priority
    TIMEOUTS = {
        "P1": 30,   # 30 seconds for emergency
        "P2": 60,   # 1 minute for urgent
        "P3": 120,  # 2 minutes for important
        "P4": 300,  # 5 minutes for routine
    }
    
    def __init__(self):
        self._queue: Dict[str, QueuedPage] = {}
        self._callbacks: List[Callable] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def add_callback(self, callback: Callable[[str, QueuedPage], None]):
        """Add a callback for queue state changes."""
        self._callbacks.append(callback)
    
    def _notify(self, event: str, page: QueuedPage):
        """Notify all callbacks of a queue event."""
        for callback in self._callbacks:
            try:
                callback(event, page)
            except Exception:
                pass
    
    async def start(self):
        """Start the queue monitor loop."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop(self):
        """Stop the queue monitor loop."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_loop(self):
        """Main monitoring loop - checks for timeouts every 5 seconds."""
        while self._running:
            try:
                await self._check_timeouts()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[QueueManager] Monitor error: {e}")
                await asyncio.sleep(5)
    
    async def _check_timeouts(self):
        """Check all queued pages for timeouts and escalate if needed."""
        pages_to_escalate: List[QueuedPage] = []
        
        for page in list(self._queue.values()):
            if page.status == PageStatus.PENDING and page.is_timed_out:
                pages_to_escalate.append(page)
        
        for page in pages_to_escalate:
            await self._handle_timeout(page)
    
    async def _handle_timeout(self, page: QueuedPage):
        """Handle a page timeout - escalate or expire."""
        current_doctor = page.current_doctor
        
        # Record the timeout in history
        page.history.append({
            "event": "timeout",
            "doctor_id": current_doctor.id if current_doctor else None,
            "doctor_name": current_doctor.name if current_doctor else None,
            "timestamp": datetime.now().isoformat(),
            "wait_seconds": page.wait_time_seconds
        })
        
        if page.has_more_doctors:
            # Escalate to next doctor
            await self._escalate_page(page)
        else:
            # No more doctors - mark as expired
            page.status = PageStatus.EXPIRED
            self._notify("expired", page)
            print(f"[QueueManager] Page {page.id} EXPIRED - no doctors responded")
    
    async def _escalate_page(self, page: QueuedPage):
        """Escalate a page to the next doctor."""
        # Move to next doctor
        page.current_doctor_index += 1
        next_doctor = page.current_doctor
        
        if not next_doctor:
            page.status = PageStatus.EXPIRED
            self._notify("expired", page)
            return
        
        page.status = PageStatus.ESCALATED
        page.last_sent_at = datetime.now()
        timeout_seconds = self.TIMEOUTS.get(page.priority, 60)
        page.response_deadline = datetime.now() + timedelta(seconds=timeout_seconds)
        
        # Actually page the next doctor via backend
        try:
            backend = get_backend_client()
            alert = page.original_decision.alert
            patient_id = None
            if page.original_decision.details:
                patient_id = page.original_decision.details.get("ehr_patient")
            
            page_result = await backend.create_page(
                doctor_id=next_doctor.id,
                priority=page.priority,
                message=f"[ESCALATED] {alert.raw_text}",
                room=alert.room,
                patient_id=patient_id,
                requested_by=alert.requested_by
            )
            page.page_result = page_result
            
            # Record in history
            page.history.append({
                "event": "escalated",
                "from_doctor_id": page.doctors_list[page.current_doctor_index - 1].id,
                "to_doctor_id": next_doctor.id,
                "to_doctor_name": next_doctor.name,
                "timestamp": datetime.now().isoformat()
            })
            
            self._notify("escalated", page)
            print(f"[QueueManager] Page {page.id} escalated to {next_doctor.name}")
            
        except Exception as e:
            print(f"[QueueManager] Escalation failed: {e}")
            page.status = PageStatus.EXPIRED
            self._notify("escalation_failed", page)
    
    async def add_page(
        self,
        decision: DispatchDecision,
        backup_doctors: List[CandidateClinician],
        page_result: Optional[Dict] = None
    ) -> str:
        """
        Add a new page to the queue.
        
        Args:
            decision: The dispatch decision with primary doctor
            backup_doctors: List of backup doctors for escalation
            page_result: Result from initial page creation
        
        Returns:
            queue_id: ID for tracking this queued page
        """
        # Build doctor list: primary + backups
        doctors_list = []
        if decision.selected_clinician_id:
            primary = CandidateClinician(
                id=decision.selected_clinician_id,
                name=decision.selected_clinician_name or decision.selected_clinician_id,
                score=1.0,
                reasoning="Primary choice",
                specialty=[],
                zone=None,
                on_call=True,
                page_count_1hr=0
            )
            doctors_list.append(primary)
        
        # Add backup doctors
        for backup_id in decision.backup_clinician_ids:
            # Find in backup_doctors list
            backup = next(
                (b for b in backup_doctors if b.id == backup_id),
                None
            )
            if backup:
                doctors_list.append(backup)
            else:
                # Create minimal backup entry
                doctors_list.append(CandidateClinician(
                    id=backup_id,
                    name=backup_id,
                    score=0.5,
                    reasoning="Backup",
                    specialty=[],
                    zone=None,
                    on_call=True,
                    page_count_1hr=0
                ))
        
        if not doctors_list:
            raise ValueError("No doctors available for queue")
        
        queue_id = str(uuid.uuid4())[:8]
        timeout_seconds = self.TIMEOUTS.get(decision.priority, 60)
        
        page = QueuedPage(
            id=queue_id,
            original_decision=decision,
            priority=decision.priority,
            current_doctor_index=0,
            doctors_list=doctors_list,
            status=PageStatus.PENDING,
            last_sent_at=datetime.now(),
            response_deadline=datetime.now() + timedelta(seconds=timeout_seconds),
            page_result=page_result
        )
        
        self._queue[queue_id] = page
        self._notify("added", page)
        
        print(f"[QueueManager] Added page {queue_id} with {len(doctors_list)} doctors, timeout={timeout_seconds}s")
        return queue_id
    
    def get_page(self, queue_id: str) -> Optional[QueuedPage]:
        """Get a specific page from the queue."""
        return self._queue.get(queue_id)
    
    def get_all_pages(
        self,
        status: Optional[PageStatus] = None
    ) -> List[QueuedPage]:
        """Get all pages, optionally filtered by status."""
        pages = list(self._queue.values())
        if status:
            pages = [p for p in pages if p.status == status]
        return sorted(pages, key=lambda p: p.created_at, reverse=True)
    
    def get_queue_summary(self) -> Dict[str, Any]:
        """Get a summary of the queue for visualization."""
        pages = list(self._queue.values())
        
        return {
            "total_pages": len(pages),
            "pending": len([p for p in pages if p.status == PageStatus.PENDING]),
            "escalated": len([p for p in pages if p.status == PageStatus.ESCALATED]),
            "accepted": len([p for p in pages if p.status == PageStatus.ACCEPTED]),
            "declined": len([p for p in pages if p.status == PageStatus.DECLINED]),
            "expired": len([p for p in pages if p.status == PageStatus.EXPIRED]),
            "pages": [self._page_to_dict(p) for p in sorted(pages, key=lambda x: x.created_at, reverse=True)]
        }
    
    def _page_to_dict(self, page: QueuedPage) -> Dict[str, Any]:
        """Convert a QueuedPage to a dict for API response."""
        current = page.current_doctor
        return {
            "id": page.id,
            "status": page.status.value,
            "priority": page.priority,
            "alert_text": page.original_decision.alert.raw_text[:100] + "..." if len(page.original_decision.alert.raw_text) > 100 else page.original_decision.alert.raw_text,
            "room": page.original_decision.alert.room,
            "current_doctor": {
                "id": current.id if current else None,
                "name": current.name if current else None,
                "index": page.current_doctor_index + 1,
                "total": len(page.doctors_list)
            } if current else None,
            "all_doctors": [{"id": d.id, "name": d.name} for d in page.doctors_list],
            "wait_time_seconds": page.wait_time_seconds,
            "time_remaining_seconds": max(0, int((page.response_deadline - datetime.now()).total_seconds())) if page.response_deadline else 0,
            "timeout_seconds": self.TIMEOUTS.get(page.priority, 60),
            "created_at": page.created_at.isoformat(),
            "history": page.history
        }
    
    async def mark_response(
        self,
        queue_id: str,
        outcome: str,  # "accept" or "decline"
        doctor_id: Optional[str] = None
    ) -> bool:
        """Mark a page as responded (accepted or declined)."""
        page = self._queue.get(queue_id)
        if not page:
            return False
        
        current = page.current_doctor
        if doctor_id and current and current.id != doctor_id:
            # Wrong doctor responded
            return False
        
        if outcome == "accept":
            page.status = PageStatus.ACCEPTED
        else:
            page.status = PageStatus.DECLINED
            # Decline triggers immediate escalation if more doctors available
            if page.has_more_doctors:
                await self._escalate_page(page)
                return True
        
        page.history.append({
            "event": outcome,
            "doctor_id": current.id if current else None,
            "doctor_name": current.name if current else None,
            "timestamp": datetime.now().isoformat(),
            "wait_seconds": page.wait_time_seconds
        })
        
        self._notify(outcome, page)
        return True
    
    async def cancel_page(self, queue_id: str) -> bool:
        """Cancel a pending page (operator intervention)."""
        page = self._queue.get(queue_id)
        if not page:
            return False
        
        if page.status in (PageStatus.ACCEPTED, PageStatus.EXPIRED):
            return False
        
        page.status = PageStatus.CANCELLED
        page.history.append({
            "event": "cancelled",
            "timestamp": datetime.now().isoformat()
        })
        
        self._notify("cancelled", page)
        return True
    
    async def manual_escalate(self, queue_id: str) -> bool:
        """Manually escalate to next doctor (operator intervention)."""
        page = self._queue.get(queue_id)
        if not page:
            return False
        
        if not page.has_more_doctors:
            return False
        
        await self._escalate_page(page)
        return True
    
    def cleanup_old_pages(self, max_age_hours: int = 24):
        """Remove completed/expired pages older than max_age_hours."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        to_remove = [
            qid for qid, page in self._queue.items()
            if page.status in (PageStatus.ACCEPTED, PageStatus.EXPIRED, PageStatus.CANCELLED)
            and page.created_at < cutoff
        ]
        for qid in to_remove:
            del self._queue[qid]


# Singleton instance
_queue_manager: Optional[PageQueueManager] = None


def get_queue_manager() -> PageQueueManager:
    """Get or create the singleton queue manager."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = PageQueueManager()
    return _queue_manager
