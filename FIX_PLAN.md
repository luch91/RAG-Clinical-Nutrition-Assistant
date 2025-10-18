# Fix Plan for Step-by-Step Therapy Generation

## Problem
After step-by-step collector completes, the code falls through to old slot validation logic which:
1. Calls `craft_missing_slot_questions()` (doesn't exist → error)
2. Asks duplicate questions
3. Never generates therapy

## Root Cause
Lines 1103-1116 in chat_orchestrator.py:
```python
if response.get("step_by_step_complete"):
    # Merge data
    # Clear collector
    # Fall through to therapy generation below  ← PROBLEM: Falls into broken old code
```

## Solution
Replace "fall through" with IMMEDIATE therapy generation.

After collector completes:
1. Merge collected data → session_slots ✓
2. Build classification dict with biomarkers
3. Call `_generate_diet_therapy(merged_slots)`
4. Retrieve docs with filtered_retrieval()
5. Build prompt with build_prompt()
6. Invoke LLM (DeepSeek for therapy)
7. Format citations
8. Return complete therapy response

## Implementation
Copy therapy generation code from lines 532-573 and insert at line 1103.

This bypasses all the broken slot validation and duplicate question logic.
