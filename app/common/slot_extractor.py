# app/common/slot_extractor.py
"""
Lightweight, deterministic slot extractor used before running the Ambiguity Gate.
This intentionally uses conservative heuristics: if something is uncertain, it is left out
so the Ambiguity Gate asks the user. Add more rules over time.
"""
import re
from typing import Dict, Any

def _find_first(regex, text):
    m = re.search(regex, text, re.IGNORECASE)
    return m.group(1).strip() if m else None

def extract_slots_from_query(query: str, classification: Dict[str, Any] = None) -> Dict[str, Any]:
    q = query or ""
    slots: Dict[str, Any] = {}
    # Normalize whitespace
    q_norm = " ".join(q.split())
    q_lower = q_norm.lower()
    
    # ---------------------------
    # food_state (boiled, raw, fried, roasted, dried, fermented)
    # ---------------------------
    m = re.search(r'\b(raw|boil(?:ed)?|boiled|fried|roast(?:ed)?|dried|ferment(?:ed)?)\b', q_norm, re.IGNORECASE)
    if m:
        state = m.group(1).lower()
        if state.startswith("boil"):
            state = "boiled"
        elif state.startswith("roast"):
            state = "roasted"
        elif state.startswith("ferment"):
            state = "fermented"
        slots['food_state'] = state
    
    # ---------------------------
    # basis: per 100g / per serving
    # ---------------------------
    if re.search(r'per\s*100\s*g|/100g|per100g|per 100', q_norm, re.IGNORECASE):
        slots['basis'] = 'per_100g'
    elif re.search(r'per\s*serving|per\s*portion', q_norm, re.IGNORECASE):
        slots['basis'] = 'per_serving'
    
    # ---------------------------
    # serving size: '100 g' or '1 cup'
    # ---------------------------
    m = re.search(r'(\d{1,4}(?:\.\d+)?)\s*(g|gram|grams|kg|kg\.|ml|l|cup|cups|tbsp|tablespoon|tsp|teaspoon)\b', q_norm, re.IGNORECASE)
    if m:
        slots['serving_size'] = f"{m.group(1)} {m.group(2)}"
    
    # ---------------------------
    # age
    # ---------------------------
    m = re.search(r'\bage\s*(?:is)?\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:year|years|yrs|y/o|yo|year old|years old)\b', q_norm, re.IGNORECASE)
    if m:
        captures = [c for c in m.groups() if c]
        if captures:
            try:
                slots['age'] = int(captures[0])
            except Exception:
                pass
    
    # Fallback: message contains a bare number that likely represents age
    if 'age' not in slots:
        m = re.search(r'^\s*(\d{1,3})\s*$', q_norm)
        if m:
            try:
                age_val = int(m.group(1))
                if 0 < age_val <= 120:
                    slots['age'] = age_val
            except Exception:
                pass
    
    # ---------------------------
    # sex / gender
    # ---------------------------
    if re.search(r'\b(male|man|boy)\b', q_lower):
        slots['sex'] = 'male'
    elif re.search(r'\b(female|woman|girl)\b', q_lower):
        slots['sex'] = 'female'
    
    # ---------------------------
    # height
    # ---------------------------
    m = re.search(r'(\d{2,3}(?:\.\d+)?)\s*(cm|m)\b', q_norm, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        val_cm = int(val * 100) if unit == 'm' else int(val)
        slots['height_cm'] = val_cm
    
    # ---------------------------
    # weight
    # ---------------------------
    m = re.search(r'(\d{2,3}(?:\.\d+)?)\s*(kg|kilograms)\b', q_norm, re.IGNORECASE)
    if m:
        try:
            slots['weight_kg'] = float(m.group(1))
        except Exception:
            pass
    
    # ---------------------------
    # biomarkers
    # ---------------------------
    biomarker_keys = ['egfr','creatinine','urea','hba1c','glucose','ldl','triglycerides','potassium','sodium','magnesium']
    for bk in biomarker_keys:
        if bk in q_lower:
            slots.setdefault('key_biomarkers', {})[bk] = None
    
    # ---------------------------
    # medications
    # ---------------------------
    meds = []
    # Check for "no medication" phrases
    if re.search(r'\b(no (current )?medication|not on any medication|not taking any medication|not using any medication|no medications|none|nil|nka|nkda)\b', q_lower):
        slots['medications'] = []
    else:
        # Extract medications from phrases like "on metformin", "taking insulin", etc.
        for m in re.finditer(r'\b(?:on|taking|using|medications?:)\s*([a-zA-Z0-9,\s\-\+]+)', q_norm, re.IGNORECASE):
            candidate = m.group(1).strip()
            for part in re.split(r'[,\+\/;]', candidate):
                p = part.strip()
                if p and 1 < len(p) < 80:
                    meds.append(p)
        if meds:
            slots['medications'] = meds
    
    # ---------------------------
    # diagnosis (robust, normalized)
    # ---------------------------
    # Canonical map: each canonical has list of synonyms to match
    DISEASE_SYNONYMS = {
        "diabetes": [
            "diabetes", "type 2 diabetes", "type ii diabetes", "diabetes type 2", "t2dm", "type 1 diabetes",
            "type i diabetes", "dm", "dm2", "dm1"
        ],
        "psoriasis": ["psoriasis"],
        "eczema": ["eczema", "atopic dermatitis"],
        "dermatitis": ["dermatitis", "seborrheic dermatitis", "contact dermatitis"],
        "kidney disease": ["chronic kidney disease", "ckd", "kidney disease", "renal failure", "renal disease"],
        "hypertension": ["hypertension", "high blood pressure", "htn"],
        "autoimmune": ["autoimmune", "lupus", "sle", "systemic lupus erythematosus", "rheumatoid arthritis", "ra"],
    }
    
    # Try to pull a candidate phrase after typical cues, then normalize to canonical
    diag_phrase = None
    m = re.search(
        r'\b(?:diagnosed with|suffering from|have|having)\s+([^.?!,;]+)',
        q_norm, re.IGNORECASE
    )
    if m:
        # Stop at common continuations (and/but + another clause, self-refs, meds/allergy mentions)
        diag_phrase = re.split(
            r'\b(?:and|but)\b|(?:i\'?m|i am)\b|(?:on|taking|using)\b|allerg',
            m.group(1), flags=re.IGNORECASE
        )[0].strip().lower()
    
    # Fallback: if no phrase, search whole query
    search_space = diag_phrase if diag_phrase else q_lower
    found_canonical = None
    
    # Preserve order: first canonical whose any synonym appears wins
    for canonical, syns in DISEASE_SYNONYMS.items():
        for s in syns:
            if s in search_space:
                found_canonical = canonical
                break
        if found_canonical:
            break
    
    if found_canonical:
        slots["diagnosis"] = found_canonical
    
    # ---------------------------
    # allergies  ✅ robust parsing with cleaners & stopwords
    # ---------------------------
    allergies = []
    # Fast-path: explicit "no allergies" phrases
    if re.search(r'\b(no (known )?allerg(?:y|ies)|no allergy|not having any allergies|not allergic to anything|nka|nkda)\b', q_lower):
        slots['allergies'] = ["none"]
    else:
        # Capture after allergy cue up to a sentence boundary; then sanitize
        for m in re.finditer(r'\b(?:allergic to|allerg(?:y|ies)|react to)\s*([^.?!]+)', q_norm, re.IGNORECASE):
            candidate = m.group(1)
            # Truncate at self-references like "and I'm...", "I'm...", "I am...", or medication phrases
            candidate = re.split(
                r'\b(?:and\s+i(?:\'?m| am)|i(?:\'?m| am)\b|i\s+take|i\s+use|on\s+)', 
                candidate, 
                flags=re.IGNORECASE
            )[0]
            # Split into items by comma/; /+ or coordinator 'and'
            parts = re.split(r'[,\+\/;]|\band\b', candidate, flags=re.IGNORECASE)
            for part in parts:
                p = part.strip().lower().strip('.')
                if not p:
                    continue
                # Remove leading filler words
                p = re.sub(r'^(?:are|is|to|of|with)\s+', '', p)
                # Skip obvious noise / continuations
                if p in {"and","or","the","a","an","none","no","nil"}:
                    continue
                if re.search(r"\b(i|i'm|im|i am|on|take|taking|use|using)\b", p):
                    continue
                # Keep only food-like tokens (letters, spaces, hyphens)
                if re.fullmatch(r"[a-z][a-z\s\-]*", p):
                    allergies.append(p)
        if allergies:
            slots['allergies'] = allergies
    
    # ---------------------------
    # food comparison
    # ---------------------------
    if re.search(r'\s+vs\.?\s+|\bcompare\b', q_norm, re.IGNORECASE):
        if ' vs ' in q_norm or ' vs. ' in q_norm:
            parts = re.split(r'\s+vs\.?\s+', q_norm, flags=re.IGNORECASE)
            if len(parts) >= 2:
                left, right = parts[0].strip(), parts[1].strip()
                qleft = _find_first(r'["\']([^"\']+)["\']', left)
                qright = _find_first(r'["\']([^"\']+)["\']', right)
                slots['food_a'] = qleft or " ".join(left.split()[-3:])
                slots['food_b'] = qright or " ".join(right.split()[:3])
        else:
            m = re.search(r'compare\s+([a-zA-Z0-9\s\-\,]+)\s+(?:and|with)\s+([a-zA-Z0-9\s\-\,]+)', q_norm, re.IGNORECASE)
            if m:
                slots['food_a'] = m.group(1).strip()
                slots['food_b'] = m.group(2).strip()
    
    # ---------------------------
    # country (names + common demonyms)
    # ---------------------------
    m = re.search(r'(Nigeria|Kenya|Canada|Ghana|Uganda|Tanzania|South Africa|Nigeria_\d{4}|Kenya_\d{4}|Canada_\d{4})', q_norm, re.IGNORECASE)
    if m:
        slots['country_table'] = m.group(0).strip()
    else:
        demonyms = {
            'nigerian': 'Nigeria', 'kenyan': 'Kenya', 'canadian': 'Canada', 'ghanaian': 'Ghana',
            'ugandan': 'Uganda', 'tanzanian': 'Tanzania', 'south african': 'South Africa'
        }
        for d, ctry in demonyms.items():
            if d in q_lower:
                slots['country'] = ctry
                break
    
    return slots