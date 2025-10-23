#!/usr/bin/env python3
"""Final comprehensive gatekeeper test - Test 1.1 specifically"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.components.llm_response_manager import LLMResponseManager

print("="*80)
print("FINAL TEST 1.1: Medications Only (No Biomarkers)")
print("="*80)

llm = LLMResponseManager(dri_table_path="data/dri_table.csv")
session_id = "final_test_meds_only"

# Initial query
query = "10 year old with type 1 diabetes taking insulin"
print(f"\nQuery: {query}")

response = llm.handle_user_query(session_id, query)
session = llm._get_session(session_id)

print(f"\nInitial extraction:")
print(f"  Medications: {session['slots'].get('medications')}")
print(f"  Biomarkers: {session['slots'].get('biomarkers_detailed')}")
print(f"  Intent: {session.get('last_query_info', {}).get('label')}")

# Answer ALL followup questions, declining biomarkers
turn = 0
while response.get('status') == 'needs_slot' and turn < 15:
    turn += 1
    slot = response.get('followup', {}).get('slot')
    print(f"\nTurn {turn}: System asks for '{slot}'")

    if slot == 'medications':
        answer = "insulin"
    elif slot == 'country':
        answer = "Kenya"
    elif 'biomarker' in slot.lower() or slot in ['HbA1c', 'glucose', 'creatinine', 'biomarkers']:
        print(f"  --> User DECLINES biomarkers")
        answer = "I don't have that"
    elif slot in ['age', 'weight_kg', 'height_cm', 'allergies']:
        answer = "not available"
    else:
        answer = "no"

    print(f"  --> User answers: {answer}")
    response = llm.handle_user_query(session_id, answer)
    print(f"  --> New status: {response.get('status')}")

    # If we get downgraded, break
    if response.get('status') == 'downgraded':
        print(f"  --> DOWNGRADED! Reason: {response.get('reason')}")
        break

# Final state
session = llm._get_session(session_id)
has_meds = bool(session['slots'].get('medications')) and session['slots'].get('medications') != "user_declined"
has_biomarkers = bool(session['slots'].get('biomarkers_detailed'))

print(f"\n{'='*80}")
print("FINAL STATE")
print(f"{'='*80}")
print(f"Has medications: {has_meds}")
print(f"Has biomarkers: {has_biomarkers}")
print(f"Final status: {response.get('status')}")
print(f"Medications value: {session['slots'].get('medications')}")
print(f"Biomarkers value: {session['slots'].get('biomarkers_detailed')}")

# Test assertion
print(f"\n{'='*80}")
print("TEST EVALUATION")
print(f"{'='*80}")

if has_meds and not has_biomarkers:
    # Should be downgraded
    if response.get('status') == 'downgraded':
        print("PASS: System correctly downgraded when biomarkers declined")
        sys.exit(0)
    elif 'therapy' in str(response).lower() and 'downgrade' not in str(response).lower():
        print("FAIL: Generated therapy without biomarkers")
        print(f"Response: {response}")
        sys.exit(1)
    else:
        print(f"UNCLEAR: Status is '{response.get('status')}' with meds but no biomarkers")
        print(f"Response: {response}")
        sys.exit(1)
else:
    print(f"UNEXPECTED STATE: has_meds={has_meds}, has_biomarkers={has_biomarkers}")
    sys.exit(1)
