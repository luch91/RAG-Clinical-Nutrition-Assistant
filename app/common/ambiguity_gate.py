"""
Ambiguity Gate: validate required slots for an intent.
This is deterministic and blocks answering until minimal required slots are present.
"""
from typing import Tuple, List, Dict, Any
from app.common.slot_schema import SCHEMAS

def validate_slots(intent: str, slots: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """
    Returns (ok, missing_slots, invalid_reasons).
    - ok True if there are no missing and no invalid reasons.
    """
    specs = SCHEMAS.get(intent, [])
    missing: List[str] = []
    invalid: List[str] = []
    for s in specs:
        # Check requirement
        if s.required:
            if s.name not in slots or slots.get(s.name) in (None, "", [], {}):
                missing.append(s.name)
                continue
        # Enum validation
        if s.enum and s.name in slots:
            val = str(slots[s.name])
            if val not in s.enum:
                invalid.append(f"{s.name} must be one of {s.enum} (got '{slots[s.name]}')")
        # Number range validation
        if s.type == "number" and s.name in slots:
            try:
                n = float(slots[s.name])
                if s.min is not None and n < s.min:
                    invalid.append(f"{s.name} below minimum {s.min}")
                if s.max is not None and n > s.max:
                    invalid.append(f"{s.name} above maximum {s.max}")
            except Exception:
                invalid.append(f"{s.name} must be numeric")
    ok = (len(missing) == 0 and len(invalid) == 0)
    return ok, missing, invalid