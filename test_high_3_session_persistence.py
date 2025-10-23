#!/usr/bin/env python3
"""
HIGH TEST #3: Session Persistence Across Multiple Turns
Critical: Data must accumulate without loss or overwrites
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.components.llm_response_manager import LLMResponseManager
import json

print("="*80)
print("HIGH TEST #3: Session Persistence - Multi-Turn Data Accumulation")
print("="*80)

llm = LLMResponseManager(dri_table_path="data/dri_table.csv")
session_id = "test_persistence_123"

# Turn 1: Age and diagnosis
print("\nTurn 1: Provide age and diagnosis")
query1 = "7 years old with cystic fibrosis"
response1 = llm.handle_user_query(session_id, query1)
session = llm._get_session(session_id)
print(f"  Age: {session['slots'].get('age')}")
print(f"  Diagnosis: {session['slots'].get('diagnosis')}")
assert session['slots'].get('age') == 7, "FAIL: Age not extracted in turn 1"
assert session['slots'].get('diagnosis'), "FAIL: Diagnosis not extracted in turn 1"

# Turn 2: Add weight and height
print("\nTurn 2: Add weight and height")
query2 = "weighs 22kg, height 120cm"
response2 = llm.handle_user_query(session_id, query2)
session = llm._get_session(session_id)
print(f"  Age: {session['slots'].get('age')} (should still be 7)")
print(f"  Weight: {session['slots'].get('weight_kg')}")
print(f"  Height: {session['slots'].get('height_cm')}")
assert session['slots'].get('age') == 7, "FAIL: Age lost after turn 2!"
assert session['slots'].get('weight_kg') == 22.0, "FAIL: Weight not added"
assert session['slots'].get('height_cm') == 120.0, "FAIL: Height not added"

# Turn 3: Add medications
print("\nTurn 3: Add medications")
query3 = "Taking Creon"
response3 = llm.handle_user_query(session_id, query3)
session = llm._get_session(session_id)
print(f"  Age: {session['slots'].get('age')} (should still be 7)")
print(f"  Weight: {session['slots'].get('weight_kg')} (should still be 22)")
print(f"  Medications: {session['slots'].get('medications')}")
assert session['slots'].get('age') == 7, "FAIL: Age lost after turn 3!"
assert session['slots'].get('weight_kg') == 22.0, "FAIL: Weight lost after turn 3!"
assert 'creon' in str(session['slots'].get('medications', [])).lower(), "FAIL: Medications not added"

# Turn 4: Add biomarkers
print("\nTurn 4: Add biomarkers")
query4 = "Vitamin D is 15 ng/mL, albumin 3.2 g/dL"
response4 = llm.handle_user_query(session_id, query4)
session = llm._get_session(session_id)
print(f"  Age: {session['slots'].get('age')} (should still be 7)")
print(f"  Medications: {session['slots'].get('medications')} (should still have Creon)")
print(f"  Biomarkers: {session['slots'].get('biomarkers_detailed')}")
assert session['slots'].get('age') == 7, "FAIL: Age lost after turn 4!"
assert session['slots'].get('medications'), "FAIL: Medications lost after turn 4!"
assert session['slots'].get('biomarkers_detailed'), "FAIL: Biomarkers not added"

# Turn 5: Add country
print("\nTurn 5: Add country")
query5 = "From Kenya"
response5 = llm.handle_user_query(session_id, query5)
session = llm._get_session(session_id)
print(f"  Country: {session['slots'].get('country')}")

# Final verification - ALL data should be present
print("\n" + "="*80)
print("FINAL SESSION STATE")
print("="*80)
final_slots = session['slots']
print(json.dumps({k: v for k, v in final_slots.items() if not k.startswith('_')}, indent=2))

# Verify ALL slots are still present
checks = {
    "age": (7, final_slots.get('age')),
    "diagnosis": (True, bool(final_slots.get('diagnosis'))),
    "weight_kg": (22.0, final_slots.get('weight_kg')),
    "height_cm": (120.0, final_slots.get('height_cm')),
    "medications": (True, bool(final_slots.get('medications'))),
    "biomarkers_detailed": (True, bool(final_slots.get('biomarkers_detailed'))),
    "country": (True, bool(final_slots.get('country'))),
}

print("\n" + "="*80)
print("VERIFICATION")
print("="*80)
all_pass = True
for slot, (expected, actual) in checks.items():
    status = "PASS" if actual == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {slot}: {status} (expected={expected}, actual={actual})")

if all_pass:
    print("\nRESULT: PASS - All data persisted across 5 turns")
    sys.exit(0)
else:
    print("\nRESULT: FAIL - Data loss detected!")
    sys.exit(1)
