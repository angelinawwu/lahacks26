"""
Test script for MedPage multi-agent system.

Tests:
1. Mode detection (sparse vs rich)
2. EHR querying by room number
3. Priority classification (P1-P4)
4. Case handler functionality
5. Full dispatch pipeline
"""
import sys
sys.path.insert(0, '.')

from agents.operator_agent import (
    detect_mode, 
    extract_room, 
    extract_specialty_hint,
    lookup_ehr_by_room,
    process_alert
)
from agents.models import AlertMessage
from agents.priority_handler import classify as priority_classify
from agents.case_handler import query_clinicians, build_specialty_query, score_candidates
from tinydb import TinyDB
import json


def test_mode_detection():
    """Test sparse vs rich mode detection."""
    print("\n" + "="*60)
    print("TEST 1: MODE DETECTION (Sparse vs Rich)")
    print("="*60)
    
    test_cases = [
        # (input, expected_mode, description)
        ("code blue room 412", "sparse", "Urgent voice brief (<10 words)"),
        ("chest pain", "sparse", "Very short urgent"),
        ("patient in room 301 having stroke symptoms", "sparse", "9 words - borderline"),
        ("Patient John Doe in room 412 with acute myocardial infarction. Requesting cardiology consult for chest pain management.", "rich", "Detailed with room and context"),
        ("routine follow-up for room 301 patient Jane Smith regarding lab results and medication reconciliation needed", "rich", "Regular appointment detail"),
        ("hemorrhaging", "sparse", "Single word emergency"),
    ]
    
    for text, expected, desc in test_cases:
        mode = detect_mode(text)
        status = "✓ PASS" if mode == expected else "✗ FAIL"
        print(f"\n{status} | {desc}")
        print(f"   Input: '{text}'")
        print(f"   Expected: {expected} | Got: {mode}")
        print(f"   Word count: {len(text.split())}")


def test_room_extraction():
    """Test room number extraction from various formats."""
    print("\n" + "="*60)
    print("TEST 2: ROOM EXTRACTION")
    print("="*60)
    
    test_cases = [
        ("patient in room 412", "412", "standard format"),
        ("code blue rm 301", "301", "abbreviated rm"),
        ("go to R412 now", "412", "R prefix"),
        ("patient at 412", "412", "just number"),
        ("emergency in room 3001", "3001", "4-digit room"),
        ("no room here", None, "no room mentioned"),
    ]
    
    for text, expected, desc in test_cases:
        room = extract_room(text)
        status = "✓ PASS" if room == expected else "✗ FAIL"
        print(f"\n{status} | {desc}")
        print(f"   Input: '{text}'")
        print(f"   Expected: {expected} | Got: {room}")


def test_ehr_querying():
    """Test EHR lookup by room number."""
    print("\n" + "="*60)
    print("TEST 3: EHR QUERYING")
    print("="*60)
    
    # Test known rooms
    print("\n--- Testing known rooms with EHR data ---")
    
    room_412 = lookup_ehr_by_room("412")
    if room_412:
        print(f"✓ PASS | Room 412 found:")
        print(f"   Patient: {room_412.get('name')}")
        print(f"   Diagnosis: {room_412.get('primary_diagnosis')}")
        print(f"   Assigned team: {room_412.get('assigned_team')}")
        print(f"   Primary physician: {room_412.get('primary_physician')}")
    else:
        print("✗ FAIL | Room 412 not found (should have John Doe)")
    
    room_301 = lookup_ehr_by_room("301")
    if room_301:
        print(f"\n✓ PASS | Room 301 found:")
        print(f"   Patient: {room_301.get('name')}")
        print(f"   Diagnosis: {room_301.get('primary_diagnosis')}")
        print(f"   Assigned team: {room_301.get('assigned_team')}")
        print(f"   Primary physician: {room_301.get('primary_physician')}")
    else:
        print("✗ FAIL | Room 301 not found (should have Jane Smith)")
    
    # Test unknown room
    print("\n--- Testing unknown room ---")
    room_999 = lookup_ehr_by_room("999")
    if room_999 is None:
        print("✓ PASS | Room 999 correctly returns None (not in database)")
    else:
        print("✗ FAIL | Room 999 should return None")
    
    # Test EHR in rich vs sparse context
    print("\n--- Testing EHR integration in alerts ---")
    
    # Rich alert with room - should trigger EHR lookup
    rich_alert = AlertMessage(
        raw_text="Patient in room 412 with cardiac chest pain, needs urgent cardiology consult",
        room="412",
        specialty_hint="cardiology"
    )
    print(f"\nRich alert (room 412):")
    print(f"   Mode: {detect_mode(rich_alert.raw_text)}")
    print(f"   EHR available: {lookup_ehr_by_room(rich_alert.room) is not None}")
    
    # Sparse alert with room - should also trigger EHR lookup
    sparse_alert = AlertMessage(
        raw_text="code blue room 412",
        room="412"
    )
    print(f"\nSparse alert (room 412):")
    print(f"   Mode: {detect_mode(sparse_alert.raw_text)}")
    print(f"   EHR available: {lookup_ehr_by_room(sparse_alert.room) is not None}")


def test_priority_classification():
    """Test Priority Handler classification."""
    print("\n" + "="*60)
    print("TEST 4: PRIORITY CLASSIFICATION")
    print("="*60)
    
    test_cases = [
        # (alert_text, expected_priority_min, description)
        ("code blue room 412 cardiac arrest", "P1", "Code blue / cardiac arrest"),
        ("patient not breathing unresponsive", "P1", "Unresponsive/not breathing"),
        ("stroke symptoms room 301", "P1", "Stroke keywords"),
        ("severe chest pain STEMI", "P1", "STEMI/chest pain"),
        ("chest pain room 412", "P2", "Chest pain (urgent but not code)"),
        ("bleeding from wound needs sutures", "P2", "Bleeding/trauma"),
        ("patient requests pain medication", "P3", "Pain control (routine)"),
        ("lab follow-up needed for room 301", "P4", "Lab follow-up (routine)"),
    ]
    
    for text, expected_min, desc in test_cases:
        alert = AlertMessage(raw_text=text, room=extract_room(text))
        result = priority_classify(alert)
        
        # Check if priority matches expected (P1 should stay P1, etc.)
        priority_num = int(result.priority[1])
        expected_num = int(expected_min[1])
        
        status = "✓ PASS" if priority_num <= expected_num else "✗ FAIL"
        print(f"\n{status} | {desc}")
        print(f"   Input: '{text}'")
        print(f"   Expected: {expected_min} or higher | Got: {result.priority}")
        print(f"   Reasoning: {result.reasoning[:100]}...")
        print(f"   Guardrail flags: {result.guardrail_flags}")


def test_case_handler():
    """Test Case Handler clinician queries and scoring."""
    print("\n" + "="*60)
    print("TEST 5: CASE HANDLER")
    print("="*60)
    
    db = TinyDB("db/clinicians.json")
    
    print("\n--- Testing specialty queries ---")
    
    # Test cardiology query
    print("\nQuery: Cardiology specialists")
    cardiology_alert = AlertMessage(
        raw_text="cardiac chest pain room 412",
        room="412",
        specialty_hint="cardiology"
    )
    specialties = build_specialty_query(cardiology_alert)
    candidates = query_clinicians(db, specialties)
    print(f"   Specialties queried: {specialties}")
    print(f"   Candidates found: {len(candidates)}")
    for c in candidates[:3]:
        print(f"   - {c['name']} ({c['id']}): {c['specialty']}, zone={c['zone']}")
    
    # Test neurology query
    print("\nQuery: Neurology specialists")
    neuro_alert = AlertMessage(
        raw_text="stroke symptoms room 301",
        room="301",
        specialty_hint="neurology"
    )
    specialties = build_specialty_query(neuro_alert)
    candidates = query_clinicians(db, specialties)
    print(f"   Specialties queried: {specialties}")
    print(f"   Candidates found: {len(candidates)}")
    
    # Test scoring with zone
    print("\n--- Testing candidate scoring ---")
    target_zone = "icu"
    scored = score_candidates(candidates, target_zone, [])
    print(f"   Target zone: {target_zone}")
    print(f"   Top candidates (scored):")
    for c in scored[:3]:
        score = c.get('_score', 0)
        print(f"   - {c['name']}: score={score:.3f}, zone={c['zone']}, status={c['status']}")


def test_full_pipeline():
    """Test complete dispatch pipeline with different scenarios."""
    print("\n" + "="*60)
    print("TEST 6: FULL DISPATCH PIPELINE")
    print("="*60)
    
    scenarios = [
        {
            "name": "URGENT: Sparse voice brief (Code Blue)",
            "alert": AlertMessage(
                raw_text="code blue room 412 cardiac arrest",
                room="412"
            ),
            "expected_mode": "sparse"
        },
        {
            "name": "URGENT: Stroke with EHR lookup",
            "alert": AlertMessage(
                raw_text="stroke patient room 301",
                room="301"
            ),
            "expected_mode": "sparse"
        },
        {
            "name": "ROUTINE: Rich consult with EHR",
            "alert": AlertMessage(
                raw_text="Patient Jane Smith in room 301 with ischemic stroke history needs routine neurology follow-up for medication adjustment",
                room="301",
                specialty_hint="neurology"
            ),
            "expected_mode": "rich"
        },
        {
            "name": "ROUTINE: Cardiology consult with EHR",
            "alert": AlertMessage(
                raw_text="Requesting cardiology consult for patient in room 412 with acute myocardial infarction for post-op care review",
                room="412",
                specialty_hint="cardiology"
            ),
            "expected_mode": "rich"
        }
    ]
    
    for scenario in scenarios:
        print(f"\n{'='*50}")
        print(f"Scenario: {scenario['name']}")
        print(f"{'='*50}")
        
        alert = scenario['alert']
        mode = detect_mode(alert.raw_text)
        
        print(f"Input: '{alert.raw_text}'")
        print(f"Mode detected: {mode} (expected: {scenario['expected_mode']})")
        
        # Check EHR
        ehr = lookup_ehr_by_room(alert.room)
        if ehr:
            print(f"EHR Match: {ehr.get('name')} - {ehr.get('primary_diagnosis')}")
            print(f"Assigned team: {ehr.get('assigned_team')}")
        else:
            print("EHR Match: None")
        
        # Run priority classification
        priority = priority_classify(alert)
        print(f"Priority: {priority.priority}")
        print(f"Flags: {priority.guardrail_flags}")
        
        # Run case handler
        db = TinyDB("db/clinicians.json")
        specialties = build_specialty_query(alert)
        if ehr and ehr.get('assigned_team'):
            for team_specialty in ehr['assigned_team']:
                if team_specialty not in specialties:
                    specialties.append(team_specialty)
        
        candidates = query_clinicians(db, specialties)
        target_zone = "icu"  # Default
        scored = score_candidates(candidates, target_zone, priority.guardrail_flags)
        
        print(f"\nTop clinician candidates:")
        for c in scored[:3]:
            print(f"   - {c['name']} ({c.get('_score', 0):.3f})")


if __name__ == "__main__":
    print("="*60)
    print("MEDPAGE AGENT TESTING SUITE")
    print("="*60)
    
    try:
        test_mode_detection()
        test_room_extraction()
        test_ehr_querying()
        test_priority_classification()
        test_case_handler()
        test_full_pipeline()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETE")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
