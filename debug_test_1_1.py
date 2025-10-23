#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.components.llm_response_manager import LLMResponseManager

llm = LLMResponseManager(dri_table_path="data/dri_table.csv")
session_id = "test_meds_only_debug"

query = "10 year old with type 1 diabetes taking insulin"
print(f"Query: {query}")

response = llm.handle_user_query(session_id, query)
session = llm._get_session(session_id)

print(f"\nExtracted slots:")
print(f"  Age: {session['slots'].get('age')}")
print(f"  Diagnosis: {session['slots'].get('diagnosis')}")
print(f"  Medications: {session['slots'].get('medications')}")
print(f"  Biomarkers: {session['slots'].get('biomarkers_detailed')}")

last_query_info = session.get('last_query_info', {})
intent = last_query_info.get('label', 'unknown')
print(f"\nClassified intent: {intent}")
print(f"Response status: {response.get('status')}")

# Follow the flow
if response.get('status') == 'needs_slot':
    for turn in range(10):
        if response.get('status') != 'needs_slot':
            print(f"\nTurn {turn}: Status changed to {response.get('status')}")
            break

        slot = response.get('followup', {}).get('slot')
        print(f"\nTurn {turn+1}: System asks for '{slot}'")

        if slot == 'medications':
            print("  -> Already extracted, providing anyway: insulin")
            response = llm.handle_user_query(session_id, "insulin")
        elif slot in ['age', 'weight_kg', 'height_cm']:
            print("  -> Declining")
            response = llm.handle_user_query(session_id, "not available")
        elif slot == 'country':
            print("  -> Providing: Kenya")
            response = llm.handle_user_query(session_id, "Kenya")
        elif 'biomarker' in slot.lower() or slot in ['HbA1c', 'glucose', 'creatinine']:
            print(f"  -> CRITICAL: User declines biomarker '{slot}'")
            response = llm.handle_user_query(session_id, "I don't have that")
            print(f"  -> After declining, status: {response.get('status')}")
            break
        else:
            print(f"  -> Declining {slot}")
            response = llm.handle_user_query(session_id, "no")

# Final check
session = llm._get_session(session_id)
has_meds = bool(session['slots'].get('medications'))
has_biomarkers = bool(session['slots'].get('biomarkers_detailed'))

print(f"\n========== FINAL STATE ==========")
print(f"Has medications: {has_meds}")
print(f"Has biomarkers: {has_biomarkers}")
print(f"Final status: {response.get('status')}")
print(f"Response keys: {list(response.keys())}")

# The test expects:
# - If has_meds=True and has_biomarkers=False
# - Response should be 'downgraded' OR
# - Response should NOT contain 'therapy' without 'downgrade'

if has_meds and not has_biomarkers:
    if response.get('status') == 'downgraded':
        print("\nRESULT: PASS - System properly downgraded")
    elif 'therapy' in str(response).lower() and 'downgrade' not in str(response).lower():
        print("\nRESULT: FAIL - Contains 'therapy' without downgrade!")
        print(f"Response: {response}")
    else:
        print(f"\nRESULT: UNCLEAR - Status is '{response.get('status')}'")
        print(f"Full response: {response}")
