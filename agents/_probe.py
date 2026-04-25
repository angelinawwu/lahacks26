"""
Quick test probe for MedPage agents.

Sends a test ChatMessage to the Operator Agent and prints the response.
Useful for local testing without Agentverse/ASI:One.

Usage:
    python -m agents._probe "urgent cardiac in room 412"
    python -m agents._probe "cardiac"  # sparse mode
    python -m agents._probe "help"
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

# Add repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.operator_agent import process_alert
from agents.models import AlertMessage
import json


def main():
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "cardiac arrest room 301"
    
    print(f"Testing: {msg!r}\n")
    
    alert = AlertMessage(
        raw_text=msg,
        room=None,
        specialty_hint=None,
        mode=None,
    )
    
    try:
        decision = process_alert(alert)
        
        print("=" * 60)
        print("DISPATCH DECISION")
        print("=" * 60)
        print(f"Mode: {decision.mode}")
        print(f"Priority: {decision.priority}")
        print(f"Assigned: {decision.selected_clinician_name or 'NONE'} ({decision.selected_clinician_id or 'N/A'})")
        print(f"Reasoning: {decision.reasoning}")
        print(f"Needs Review: {decision.needs_operator_review}")
        print(f"Guardrails: {', '.join(decision.guardrail_flags)}")
        if decision.backup_clinician_ids:
            print(f"Backup: {', '.join(decision.backup_clinician_ids)}")
        print("\nDetails:")
        print(json.dumps(decision.details, indent=2, default=str))
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
