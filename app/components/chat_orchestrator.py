# app/components/chat_orchestrator.py
"""
Chat orchestrator for the Nutrition RAG chatbot.
Option B: With profile/session memory and structured outputs.
Responsibilities:
- Fast pre-classification via keyword mapper (Day 1)
- ML classification via DistilBERT (Day 1)
- Slot extraction + Ambiguity Gate (Day 1)
- Retrieval filter construction (Day 2)
- Dynamic template building (Day 3)
- Nutrient optimization & meal planning integration (Day 4)
- Profile persistence across turns
- Follow-up generation
- Sources + model transparency
"""
from typing import Dict, Any, List, Optional,Tuple
from app.components.query_classifier import NutritionQueryClassifier
from app.components.api_models import get_llm_client
from app.components.hybrid_retriever import filtered_retrieval, retriever
from app.components.nutrient_calculator import optimize_diet, meal_planner, convert_fct_rows_to_foods
from app.common.logger import get_logger
# Day 1 & Day 2
from app.common.slot_extractor import extract_slots_from_query
from app.common.ambiguity_gate import validate_slots
from app.common.retrieval_filters import build_filters
# Day 3
from app.common.templates import build_prompt
# Follow-up generator
from app.components.followup_question_generator import FollowUpQuestionGenerator

logger = get_logger(__name__)

# ---------------------------
# Keyword Mapper (Fast Pre-Classifier)
# ---------------------------
KEYWORD_MAP = {
    "vegetarian": "vegetarian",
    "vegan": "vegetarian",
    "allergy": "allergy",
    "intolerance": "allergy",
    "phenylketonuria": "IEM",
    "pku": "IEM",
    "inborn error": "IEM",
    "renal": "renal",
    "kidney": "renal",
    "sports": "sports",
    "athlete": "sports",
    "training": "sports",
    # Skin-related
    "acne": "skincare",
    "eczema": "skincare",
    "psoriasis": "skincare",
    "dermatitis": "skincare",
    "rash": "skincare",
    "skin": "skincare",
    # Autoimmune examples
    "lupus": "therapy",
    "sle": "therapy",
    "autoimmune": "therapy",
}

class ChatOrchestrator:
    def __init__(self) -> None:
        self.classifier = NutritionQueryClassifier()
        # Conversational follow-ups handled inline (one question per turn)
        self.session_slots: Dict[str, Any] = {}  # Persist user profile info
        self._intent_lock: Optional[str] = None  # Lock intent across follow-up turns
        self._awaiting_slot: Optional[str] = None  # Single required slot we asked for last turn
        self._awaiting_question: Optional[str] = None  # Track the exact question asked
        self._retry_count: int = 0  # Track retry attempts for current slot
        self._max_retries: int = 3  # Maximum retries before offering skip
        self._awaiting_confirmation: bool = False  # Track if waiting for yes/no confirmation
        self._pending_medications: List[str] = []  # Store medications pending confirmation
        self._medication_suggestions: List[Dict[str, Any]] = []  # Store spelling suggestions
        self._meal_plan_consent: bool = False  # Track meal plan consent state
        # Initialize follow-up question generator
        self.follow_up_generator = FollowUpQuestionGenerator()
        # Medication validation cache (in-memory)
        self._medication_cache: Dict[str, Dict[str, Any]] = {}
    
    # ---------------------------
    # Meal plan helpers (consent-based)
    # ---------------------------
    def _wants_meal_plan(self, text: str) -> bool:
        q = (text or "").lower()
        return any(k in q for k in ["meal plan", "diet plan", "7-day plan", "7 day plan", "1-day plan", "1 day plan", "plan my meals"])
    
    def _parse_meal_plan_days(self, text: str) -> Optional[int]:
        q = (text or "").lower()
        if "7" in q or "seven" in q:
            return 7
        if "1" in q or "one" in q or "single day" in q:
            return 1
        return None
    
    def _timing_notes_for_meds(self, meds: List[str]) -> List[str]:
        notes: List[str] = []
        meds_l = [m.lower() for m in (meds or [])]
        if any("levodopa" in m or "l-dopa" in m for m in meds_l):
            notes.append("Separate levodopa from high-protein meals by 1–2 hours; consider taking 30–60 min before meals.")
        if any("levothyroxine" in m or "thyroxine" in m for m in meds_l):
            notes.append("Take levothyroxine on an empty stomach; avoid calcium/iron supplements within 4 hours.")
        if any("iron" in m and "ferrous" in m for m in meds_l) or any(m.strip()=="iron" for m in meds_l):
            notes.append("Take iron with vitamin C; avoid tea/coffee and calcium around dosing time.")
        return notes
    
    def _build_meal_plan(self, slots: Dict[str, Any], days: int = 1) -> Dict[str, Any]:
        # Build retrieval filters focusing on country table when available
        filter_candidates = build_filters("therapy", slots)
        filters = filter_candidates.get("filters", {})
        try:
            docs = filtered_retrieval(
                "staple foods for diet planning",
                filters,
                k=18,
                sources=["Food Composition Tables"],
            )
        except Exception:
            docs = []
        rows = [getattr(d, "metadata", {}) for d in (docs or [])]
        foods = convert_fct_rows_to_foods(rows)
        # Targets
        targets = self._generate_diet_therapy(slots).get("nutrient_targets", {})
        allergies = slots.get("allergies") or []
        try:
            optimized = optimize_diet(foods, targets, allergies=allergies)
        except Exception:
            optimized = {"diet_plan": [], "note": "Optimization failed."}
        try:
            one_day = meal_planner(foods, targets, allergies=allergies)
        except Exception:
            one_day = {"meals": {}, "shopping_list": {}, "total_grams": 0}
        weekly_plan = None
        if days and days >= 7:
            base_meals = one_day.get("meals", {})
            weekly_plan = []
            for i in range(7):
                weekly_plan.append({"day": f"Day {i+1}", "meals": base_meals})
        timing_notes = self._timing_notes_for_meds(slots.get("medications", []))
        # Build citations for the plan docs
        plan_citations: List[Dict[str, Any]] = []
        for d in (docs or []):
            meta = getattr(d, "metadata", {}) or {}
            sid = meta.get("source_id") or meta.get("id") or None
            page = meta.get("page") or meta.get("page_no") or None
            ref = f"{sid}:{page}" if sid and page else sid or page
            plan_citations.append({
                "type": "fct",
                "food": meta.get("food") or meta.get("food_name"),
                "country_label": meta.get("country") or meta.get("country_table") or meta.get("table_country"),
                "source": meta.get("source") or meta.get("country_table") or "Food Composition Tables",
                "ref": ref,
            })
        return {
            "optimized_plan": optimized,
            "meals": one_day.get("meals", {}),
            "shopping_list": one_day.get("shopping_list", {}),
            "total_grams": one_day.get("total_grams", 0),
            "weekly_plan": weekly_plan,
            "timing_notes": timing_notes,
            "_fct_used": bool(foods),
            "citations": plan_citations,
        }
    
    # ---------------------------
    # Session reset
    # ---------------------------
    def reset_session(self) -> Dict[str, Any]:
        self.session_slots = {}
        self._intent_lock = None
        self._awaiting_slot = None
        self._awaiting_question = None
        self._retry_count = 0
        self._awaiting_confirmation = False
        self._meal_plan_consent = False
        # Return a clean message (avoid encoding artifacts)
        msg = "Session reset. I've cleared stored profile (country, age, BMI, etc.)."
        return {"message": msg}
    
    # ---------------------------
    # Medication validation using RxNorm API (FREE)
    # ---------------------------
    def _validate_medications(self, medications: List[str]) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Validate medications using RxNorm API (National Library of Medicine - FREE).
        Returns: (corrected_medications, suggestions)

        suggestions format:
        [{
            "original": "metformn",
            "suggested": "metformin",
            "confidence": 0.95,
            "alternatives": ["metformin hydrochloride"]
        }]
        """
        from app.config.config import (
            ENABLE_MEDICATION_VALIDATION,
            MEDICATION_API_TIMEOUT,
            MEDICATION_VALIDATION_CONFIDENCE
        )
        import requests

        # If validation disabled, return as-is
        if not ENABLE_MEDICATION_VALIDATION:
            return medications, []

        corrected = []
        suggestions = []

        for med in medications:
            med_lower = med.lower().strip()

            # Skip placeholders
            if med_lower in ["none", "nil", "no", ""]:
                continue

            # Check cache first
            if med_lower in self._medication_cache:
                cached = self._medication_cache[med_lower]
                corrected.append(cached.get("corrected_name", med))
                if cached.get("suggestion"):
                    suggestions.append(cached["suggestion"])
                continue

            try:
                # Try approximate term match (handles typos)
                response = requests.get(
                    "https://rxnav.nlm.nih.gov/REST/approximateTerm.json",
                    params={"term": med, "maxEntries": 3},
                    timeout=MEDICATION_API_TIMEOUT
                )

                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("approximateGroup", {}).get("candidate", [])

                    if candidates:
                        best_match = candidates[0]
                        confidence = best_match.get("score", 0) / 100.0
                        suggested_name = best_match.get("name", "")

                        if confidence >= MEDICATION_VALIDATION_CONFIDENCE:
                            # High confidence match
                            corrected.append(suggested_name)

                            # Add to suggestions if spelling differs
                            if med.lower() != suggested_name.lower():
                                suggestion = {
                                    "original": med,
                                    "suggested": suggested_name,
                                    "confidence": confidence,
                                    "alternatives": [c.get("name") for c in candidates[1:3] if c.get("name")]
                                }
                                suggestions.append(suggestion)

                                # Cache the result
                                self._medication_cache[med_lower] = {
                                    "corrected_name": suggested_name,
                                    "suggestion": suggestion
                                }
                            else:
                                # Exact match - cache without suggestion
                                corrected.append(suggested_name)
                                self._medication_cache[med_lower] = {
                                    "corrected_name": suggested_name,
                                    "suggestion": None
                                }
                        else:
                            # Low confidence - keep original but warn
                            corrected.append(med)
                            suggestions.append({
                                "original": med,
                                "suggested": None,
                                "confidence": confidence,
                                "error": f"Low confidence match ({confidence:.0%}). Please verify spelling."
                            })
                    else:
                        # No match found
                        corrected.append(med)
                        suggestions.append({
                            "original": med,
                            "suggested": None,
                            "confidence": 0.0,
                            "error": "Medication not found in database. Please verify spelling."
                        })
                else:
                    # API error - keep original
                    logger.warning(f"RxNorm API returned status {response.status_code} for '{med}'")
                    corrected.append(med)

            except requests.exceptions.Timeout:
                logger.warning(f"RxNorm API timeout for '{med}' - using original")
                corrected.append(med)
            except Exception as e:
                logger.warning(f"Medication validation failed for '{med}': {str(e)}")
                corrected.append(med)  # Fallback: keep original

        return corrected, suggestions

    # ---------------------------
    # Progress indicator helper
    # ---------------------------
    def _get_progress_indicator(self, template_key: str, merged_slots: Dict[str, Any]) -> str:
        """Generate progress indicator showing N of M required fields completed"""
        from app.common.slot_schema import SCHEMAS
        specs = SCHEMAS.get(template_key, [])
        required_slots = [s.name for s in specs if s.required]

        if not required_slots:
            return ""

        completed = sum(1 for slot in required_slots if slot in merged_slots and merged_slots[slot] not in (None, "", [], {}))
        total = len(required_slots)

        if completed < total:
            return f" ({completed + 1}/{total} required)"
        return ""

    # ---------------------------
    # Enhanced response parser with context understanding
    # ---------------------------
    def _parse_user_response(self, answer_text: str, slot: str) -> Tuple[Any, str]:
        """
        Parse user response with context awareness.
        Returns (coerced_value, status) where status is:
        - "success": Value parsed successfully
        - "need_details": User confirmed but didn't provide details (e.g., "yes")
        - "not_available": User doesn't have the information
        - "skip_requested": User wants to skip this question
        - "failed": Couldn't parse the response
        """
        import re
        low = answer_text.lower().strip()

        # Check for "not available" / "unknown" responses
        not_available_phrases = [
            "not available", "don't have", "don't know", "unknown",
            "not sure", "no idea", "can't remember", "unavailable",
            "n/a", "na", "not applicable"
        ]
        if any(phrase in low for phrase in not_available_phrases):
            return None, "not_available"

        # Check for skip requests
        skip_phrases = ["skip", "skip this", "later", "pass", "next question"]
        if any(phrase in low for phrase in skip_phrases):
            return None, "skip_requested"

        # Parse based on slot type
        if slot == "age":
            m = re.search(r'(\d{1,3})', answer_text)
            if m:
                age_val = int(m.group(1))
                if 0 <= age_val <= 120:
                    return age_val, "success"
            return None, "failed"

        elif slot in ("height_cm", "weight_kg"):
            m = re.search(r'(\d{1,3}(?:\.\d+)?)', answer_text)
            if m:
                val = float(m.group(1))
                if slot == "height_cm":
                    if 50 <= val <= 250:
                        return int(val), "success"
                else:  # weight_kg
                    if 10 <= val <= 400:
                        return val, "success"
            return None, "failed"

        elif slot == "sex":
            if any(x in low for x in ["male", "man", "boy", "m"]):
                return "male", "success"
            elif any(x in low for x in ["female", "woman", "girl", "f"]):
                return "female", "success"
            return None, "failed"

        elif slot in ("allergies", "medications"):
            # Check for explicit "none" responses
            none_phrases = [
                "none", "nil", "no", "nope", "no allergy", "no allergies",
                "nka", "nkda", "not on any medication", "no medication",
                "not having any allergies", "not allergic to anything",
                "no medications", "not taking any"
            ]
            if low in none_phrases or low == "0":
                return ["none"] if slot == "allergies" else [], "success"

            # Check for confirmation without details
            yes_phrases = ["yes", "yeah", "yep", "yup", "i do", "i am", "i have"]
            if low in yes_phrases:
                return None, "need_details"

            # Parse list of items
            if answer_text and answer_text not in yes_phrases:
                parts = [p.strip() for p in answer_text.replace("/", ",").replace("+", ",").split(",")]
                items = [p for p in parts if p and len(p) > 1]

                if items and slot == "medications":
                    # Validate medications using RxNorm API
                    corrected, suggestions = self._validate_medications(items)

                    if suggestions:
                        # Found spelling corrections - need confirmation
                        self._pending_medications = corrected
                        self._medication_suggestions = suggestions
                        return None, "needs_medication_confirmation"
                    else:
                        # No corrections needed or validation disabled
                        return corrected if corrected else items, "success"
                elif items:
                    # Allergies or other lists - no validation
                    return items, "success"

            return None, "failed"

        elif slot == "diagnosis":
            if answer_text and len(answer_text) > 2:
                return answer_text.strip(), "success"
            return None, "failed"

        elif slot in ("country", "country_table"):
            if answer_text and len(answer_text) > 1:
                return answer_text.strip(), "success"
            return None, "failed"

        elif slot == "key_biomarkers":
            # Check for yes/no
            if low in ["yes", "yeah", "yep", "i have", "i do"]:
                return None, "need_details"
            elif low in ["no", "nope", "don't have", "none"]:
                return {}, "success"  # Empty dict for no biomarkers

            # Try to parse biomarker values
            biomarkers = {}
            # Look for patterns like "HbA1c 8.5" or "eGFR: 45"
            for match in re.finditer(r'(egfr|hba1c|creatinine|glucose|ldl|hdl|triglycerides|potassium|sodium)\s*[:=]?\s*(\d+(?:\.\d+)?)', low):
                biomarkers[match.group(1)] = float(match.group(2))

            if biomarkers:
                return biomarkers, "success"

            return None, "failed"

        # Default: try to accept as string
        if answer_text and len(answer_text) > 0:
            return answer_text.strip(), "success"

        return None, "failed"

    # ---------------------------
    # Pre-classifier
    # ---------------------------
    def _pre_classify(self, query: str) -> str:
        q = (query or "").lower()
        for kw, cat in KEYWORD_MAP.items():
            if kw in q:
                if cat == "skincare":
                    if any(dt in q for dt in ["eczema", "psoriasis", "dermatitis", "infection", "fungal", "skin disease"]):
                        return "dermatology"  # therapy-like handling
                    return "skincare"
                return cat
        return ""
    
    # ---------------------------
    # Minimal therapy target generator (age-based defaults)
    # ---------------------------
    def _generate_diet_therapy(self, slots: Dict[str, Any]) -> Dict[str, Any]:
        """Generate simple nutrient targets with age-based defaults.
        - If weight/height present, prefer provided values; otherwise fall back to age group defaults.
        - Returns a structure compatible with the Therapy Summary renderer.
        """
        age = slots.get("age")
        sex = (slots.get("sex") or "").lower()
        weight = slots.get("weight_kg") or slots.get("weight")
        height = slots.get("height_cm") or slots.get("height")
        try:
            age_val = int(age) if age is not None else None
        except Exception:
            age_val = None
        is_adult = (age_val is None) or (age_val >= 18)
        if weight is None:
            weight = 60 if sex == "female" else 70 if is_adult else 30
        if height is None:
            height = 165 if sex == "female" else 175 if is_adult else 130
        energy_kcal = 2000 if is_adult else 1400
        try:
            w = float(weight)
            protein_g = max(45, round(0.8 * w)) if is_adult else max(30, round(1.0 * w))
        except Exception:
            protein_g = 50 if is_adult else 30
        targets = {
            "energy_kcal": energy_kcal,
            "macros": {"protein_g": protein_g},
            "micros": {},
        }
        therapy_output: Dict[str, Any] = {
            "nutrient_targets": targets,
            "biochemical_rationale": self._biochemical_rationale(slots, targets),
            "drug_nutrient_interactions": [],
            "optimized_plan": {},
        }
        return therapy_output
    
    # ---------------------------
    # Decide if FCT is needed
    # ---------------------------
    def _should_use_fct(self, intent: str, query: str, slots: Dict[str, Any]) -> bool:
        if intent == "comparison":
            return True
        if intent in ["recommendation", "therapy", "dermatology"]:
            if any(kw in (query or "").lower() for kw in ["food", "eat", "meal", "diet", "recipe", "source"]):
                return bool(slots.get("food") or slots.get("country") or slots.get("food_a") or slots.get("food_b"))
        return False
    
    # ---------------------------
    # Source routing
    # ---------------------------
    def _select_sources(
        self, intent: str, subtype: Optional[str] = None, slots: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        SOURCE_ROUTER: Dict[str, Any] = {
            "comparison": ["Food Composition Tables"],
            "recommendation": {
                "vegetarian": ["Plant-Based Nutrition in Clinical Practice 2022", "Food Composition Tables"],
                "pediatric": ["Clinical Paediatric Dietetics (2020)", "Clinical Nutrition"],
                "pregnancy": ["Clinical Nutrition", "Pregnancy guidelines"],
                "skincare": ["Nutrition for Healthy Skin (2011)", "Forever Young (2010)"],
                "sports": ["Clinical Sports Nutrition (2021)", "Clinical Nutrition in Athletic Training"],
                "general": ["Dietary Reference Intakes", "Guidelines", "Clinical Nutrition"],
            },
            "therapy": {
                "diabetes": ["Clinical Nutrition", "Nutrition and Diet Therapy"],
                "renal": ["Clinical Nutrition", "Nutrition and Diet Therapy"],
                "cancer": ["Oncology Nutrition for Clinical Practice", "Clinical Nutrition"],
                "autoimmune": ["Clinical Nutrition"],
                "pediatric": ["Clinical Paediatric Dietetics"],
                "dermatology": ["Clinical Nutrition", "Nutrition for Healthy Skin (2011)"],
                "general": ["Clinical Nutrition", "Diet Therapy"],
            },
            "nutrigenomics": ["Principles of Nutrigenetics and Nutrigenomics", "Nutrigenomics texts"],
            "sports": ["Clinical Sports Nutrition (2021)", "Clinical Nutrition in Athletic Training"],
            "skincare": ["Nutrition for Healthy Skin (2011)", "Forever Young (2010)"],
            "general": ["Guidelines", "Clinical Nutrition"],
        }
        BIOCHEMISTRY_LAYER = [
            "Integrative Human Biochemistry",
            "Handbook of Vitamins",
            "Nutrigenomics (biochemical explanations)",
        ]
        if intent in SOURCE_ROUTER:
            mapped = SOURCE_ROUTER[intent]
            sources = list(mapped.get(subtype, mapped.get("general", []))) if isinstance(mapped, dict) else list(mapped)
        else:
            sources = list(SOURCE_ROUTER["general"])
        sources += BIOCHEMISTRY_LAYER
        if slots and slots.get("medications"):
            sources += ["Drug-Nutrient Interactions", "Handbook of Drug-Nutrient Interaction"]
        seen, deduped = set(), []
        for s in sources:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        return deduped
    
    # ---------------------------
    # Biochemical rationale
    # ---------------------------
    def _biochemical_rationale(self, slots: Dict[str, Any], targets: Dict[str, Any]) -> List[Dict[str, str]]:
        dx = (slots.get("diagnosis") or "").lower()
        rationales: List[Dict[str, str]] = []
        def add(nutrient: str, text: str) -> None:
            rationales.append(
                {
                    "nutrient": nutrient,
                    "why": text,
                    "sources_hint": ["Integrative Human Biochemistry", "Handbook of Vitamins"],
                }
            )
        add("Energy (kcal)", "Meets basal and activity needs; chronic deficits impair immune and skin barrier function.")
        if targets.get("macros", {}).get("protein_g"):
            add("Protein", "Supports enzyme function, immune mediators, collagen/keratin synthesis, and tissue repair.")
        if targets.get("micros", {}).get("vitamin_c"):
            add("Vitamin C", "Cofactor in collagen synthesis; enhances iron absorption; antioxidant.")
        if targets.get("micros", {}).get("zinc"):
            add("Zinc", "Supports DNA repair, keratinocyte function, and immunity.")
        if targets.get("micros", {}).get("iron"):
            add("Iron", "Essential for oxygen delivery and immune energetics.")
        if targets.get("micros", {}).get("calcium"):
            add("Calcium", "Cell signaling, neuromuscular function, and vitamin D interaction.")
        if "diab" in dx:
            add("Carbohydrate quality", "Lower glycemic load reduces insulin demand and improves satiety.")
        if "renal" in dx or "ckd" in dx:
            add("Mineral balance", "Adjust electrolytes by stage; moderate protein reduces nitrogenous waste.")
        if any(k in dx for k in ["eczema", "psoriasis", "dermatitis"]):
            add("Omega-3 & antioxidants", "Anti-inflammatory mediators support skin health.")
        return rationales
    
    # ---------------------------
    # Therapy summary
    # ---------------------------
    def _summarize_therapy_output(self, slots: Dict[str, Any], therapy_output: Dict[str, Any]) -> str:
        if not therapy_output:
            return "⚠️ No therapy plan available."
        lines, profile_bits = [], []
        if slots.get("age"):
            profile_bits.append(f"{slots['age']} yrs")
        if slots.get("sex"):
            profile_bits.append(slots["sex"].capitalize())
        if slots.get("diagnosis"):
            profile_bits.append(f"Diagnosis: {slots['diagnosis']}")
        if slots.get("allergies"):
            profile_bits.append(f"Allergies: {', '.join(slots['allergies'])}")
        if slots.get("medications"):
            profile_bits.append(f"Meds: {', '.join(slots['medications'])}")
        if profile_bits:
            lines.append("**Profile:** " + "; ".join(profile_bits))
        t = therapy_output.get("nutrient_targets", {})
        macros, micros = t.get("macros", {}), t.get("micros", {})
        lines.append(f"**Energy target:** {t.get('energy_kcal', '?')} kcal")
        if macros:
            lines.append(f"**Protein:** {macros.get('protein_g', '?')} g/day")
        if micros:
            highlights = [f"{k.capitalize()}: {v}" for k, v in micros.items()]
            lines.append("**Key micros:** " + ", ".join(highlights))
        rationale = therapy_output.get("biochemical_rationale", [])
        if rationale:
            lines.append("**Rationale:** " + " | ".join([f"{r['nutrient']}: {r['why']}" for r in rationale[:2]]))
        dni = therapy_output.get("drug_nutrient_interactions", [])
        if dni:
            lines.append(
                "**Drug–Nutrient Interactions:** "
                + "; ".join([f"{r['medication_match']}: {r['interaction']}" for r in dni])
            )
        diet_plan = therapy_output.get("optimized_plan", {}).get("diet_plan", [])
        if diet_plan:
            foods = [f"{f['food']} ({int(f['portion_g'])}g)" for f in diet_plan[:3]]
            lines.append("**Suggested foods:** " + ", ".join(foods))
        out = "\n".join(lines)
        # Clean any encoding artifacts that might slip in
        out = out.replace("Drug ?\"Nutrient", "Drug–Nutrient")
        return out
    
    # ---------------------------
    # Centralized safety validation layer
    # ---------------------------
    def _validate_response_safety(self, answer: str, slots: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Central safety validation layer that blocks unsafe responses before they're sent.
        Returns (is_valid, error_message)
        """
        # 1. Medical disclaimer check
        disclaimer = "For educational purposes only. Not medical advice. Consult a healthcare provider."
        if disclaimer not in answer:
            return False, "Medical disclaimer missing"
        
        # 2. Allergy enforcement check
        if slots.get("allergies"):
            allergies = [a.lower() for a in slots["allergies"] if a and a not in ("none", "no", "nil", "n/a")]
            for allergen in allergies:
                if allergen in answer.lower():
                    return False, f"Allergen '{allergen}' found in response"
        
        # 3. Medication-first check
        if "therapy" in slots.get("intent", "") and not slots.get("medications"):
            return False, "Therapy response generated without medications confirmation"
        
        # 4. Meal plan consent check
        if "meal plan" in answer.lower() and not slots.get("meal_plan_consent"):
            return False, "Meal plan generated without explicit consent"
        
        # 5. FCT unavailability check
        if "fct_unavailable" in slots.get("warnings", []) and "using defaults" not in answer.lower():
            return False, "FCT unavailable but response doesn't indicate using defaults"
        
        return True, "All safety checks passed"
    
    # ---------------------------
    # Main handler
    # ---------------------------
    def handle_query(self, query: str) -> Dict[str, Any]:
        if (query or "").strip().lower() in ["reset session", "new topic", "start over"]:
            return self.reset_session()
        
        # If we are awaiting a specific slot from the previous turn, do not reclassify intent
        pre_key = None
        classification = {"label": "general"}
        if self._awaiting_slot and self._intent_lock:
            template_key = self._intent_lock
        else:
            pre_key = self._pre_classify(query)
            try:
                classification = self.classifier.classify(query)
            except Exception:
                classification = {"label": "general"}
            template_key = pre_key or classification.get("label", "general")
            # On first turn, lock the intent so follow-ups don't jump intents
            self._intent_lock = self._intent_lock or template_key
        
        # CRITICAL: High-risk query handling
        if classification.get("is_high_risk", False):
            return {
                "template": "followup",
                "answer": "I notice this may be a high-risk query. Are you under the care of a healthcare provider?",
                "followups": [],
                "model_used": "none",
                "therapy_output": None,
                "therapy_summary": None,
                "sources_used": [],
                "model_note": "High-risk query",
                "warnings": ["high_risk"],
            }
        
        # If we asked a specific question in the last turn, use enhanced parser
        if self._awaiting_slot:
            answer_text = (query or "").strip()
            slot = self._awaiting_slot

            # Special handling: If awaiting confirmation for medications
            if self._awaiting_confirmation and slot == "medications" and self._pending_medications:
                low = answer_text.lower().strip()
                if low in ["yes", "yeah", "yep", "correct", "ok", "okay", "y"]:
                    # User confirmed the corrected medications
                    slots = {slot: self._pending_medications}
                    self.session_slots[slot] = self._pending_medications
                    self._awaiting_slot = None
                    self._awaiting_question = None
                    self._retry_count = 0
                    self._awaiting_confirmation = False
                    self._pending_medications = []
                    self._medication_suggestions = []
                    logger.info(f"Medication spellings confirmed: {self._pending_medications}")
                    # Fall through to continue
                elif low in ["no", "nope", "incorrect", "n"]:
                    # User rejected - ask them to re-enter
                    self._awaiting_confirmation = False
                    self._pending_medications = []
                    self._medication_suggestions = []
                    return {
                        "template": "followup",
                        "answer": "Please re-enter your medications with correct spelling (separate with commas):",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Re-entering medications",
                        "warnings": ["medication_validation"],
                        "composer_placeholder": "List medications"
                    }
                else:
                    # Unclear response - ask again
                    return {
                        "template": "followup",
                        "answer": "Please answer 'yes' or 'no' to confirm the medication spellings:",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Awaiting yes/no confirmation",
                        "warnings": ["medication_validation"],
                        "composer_placeholder": "yes or no"
                    }

            # Use enhanced parser
            coerced, status = self._parse_user_response(answer_text, slot)

            slots = {}

            # Handle based on parse status
            if status == "success":
                # Successfully parsed - save and move on
                slots[self._awaiting_slot] = coerced
                self.session_slots[self._awaiting_slot] = coerced
                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0
                self._awaiting_confirmation = False
                # Fall through to continue with next question or final answer

            elif status == "needs_medication_confirmation":
                # Medications parsed but need spelling confirmation
                suggestions = self._medication_suggestions

                # Build confirmation message
                corrections = []
                errors = []
                for s in suggestions:
                    if s.get("suggested"):
                        corrections.append(f"  • {s['original']} → {s['suggested']}")
                    elif s.get("error"):
                        errors.append(f"  • {s['original']}: {s['error']}")

                if corrections or errors:
                    msg_parts = []
                    if corrections:
                        msg_parts.append("I found these medications. Did you mean:\n" + "\n".join(corrections))
                    if errors:
                        msg_parts.append("\n⚠️ Warnings:\n" + "\n".join(errors))

                    confirm_msg = "\n".join(msg_parts) + "\n\nIs this correct? (yes/no)"

                    self._awaiting_confirmation = True
                    return {
                        "template": "followup",
                        "answer": confirm_msg,
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Confirming medication spellings",
                        "warnings": ["medication_validation"],
                        "composer_placeholder": "yes or no"
                    }

            elif status == "need_details":
                # User said "yes" but didn't provide details - ask for specifics
                self._awaiting_confirmation = False  # No longer waiting for confirmation
                detail_prompts = {
                    "medications": "Please list your medications (e.g., metformin, lisinopril). Separate multiple with commas:",
                    "allergies": "Please list your food allergies (e.g., peanuts, dairy, shellfish). Separate multiple with commas:",
                    "key_biomarkers": "Please provide your lab results (e.g., HbA1c 8.5, eGFR 45, creatinine 2.0):"
                }
                follow_up = detail_prompts.get(slot, f"Please provide your {slot.replace('_', ' ')}:")
                return {
                    "template": "followup",
                    "answer": follow_up,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": "Awaiting details",
                    "warnings": ["missing_data"],
                    "composer_placeholder": follow_up
                }

            elif status == "not_available":
                # User doesn't have this information
                # Check if slot is optional
                from app.common.slot_schema import SCHEMAS
                specs = SCHEMAS.get(template_key, [])
                slot_spec = next((s for s in specs if s.name == slot), None)

                if slot_spec and not slot_spec.required:
                    # Optional slot - skip it
                    logger.info(f"Skipping optional slot '{slot}' - not available")
                    self._awaiting_slot = None
                    self._awaiting_question = None
                    self._retry_count = 0
                    # Fall through to next question
                elif slot == "key_biomarkers":
                    # Biomarkers often unavailable - use empty dict
                    slots[slot] = {}
                    self.session_slots[slot] = {}
                    self._awaiting_slot = None
                    self._awaiting_question = None
                    self._retry_count = 0
                    logger.info(f"Biomarkers not available - continuing with defaults")
                else:
                    # Required slot - offer to continue with defaults
                    return {
                        "template": "followup",
                        "answer": f"This information helps provide safer recommendations. Would you like to continue with default values for {slot.replace('_', ' ')}? (yes/no)",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Confirming default use",
                        "warnings": ["missing_data"],
                        "composer_placeholder": "yes or no"
                    }

            elif status == "skip_requested":
                # User explicitly wants to skip - move on
                logger.info(f"User requested skip for slot '{slot}'")
                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0
                # Fall through to next question

            else:  # status == "failed"
                # Parsing failed - increment retry count
                self._retry_count += 1

                if self._retry_count >= self._max_retries:
                    # Max retries reached - offer to skip or use default
                    return {
                        "template": "followup",
                        "answer": f"I'm having trouble understanding that. Would you like to skip this question or provide a different answer? (Type 'skip' to skip)",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Max retries reached",
                        "warnings": ["parsing_failed"],
                        "composer_placeholder": "Your answer or 'skip'"
                    }
                else:
                    # Retry with clarification
                    retry_prompts = {
                        "age": "Please provide your age as a number (e.g., 30):",
                        "height_cm": "Please provide your height in centimeters (e.g., 170):",
                        "weight_kg": "Please provide your weight in kilograms (e.g., 70):",
                        "sex": "Please specify: male or female:",
                        "medications": "Please list medications separated by commas (or type 'none'):",
                        "allergies": "Please list allergies separated by commas (or type 'none'):",
                        "diagnosis": "Please provide your medical condition or diagnosis:",
                        "country": "Please specify a country (e.g., Nigeria, Kenya, Canada):",
                    }
                    clarification = retry_prompts.get(slot, f"Could you please clarify your {slot.replace('_', ' ')}?")
                    return {
                        "template": "followup",
                        "answer": clarification,
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": f"Retry {self._retry_count}/{self._max_retries}",
                        "warnings": ["parsing_failed"],
                        "composer_placeholder": clarification
                    }
        else:
            try:
                slots = extract_slots_from_query(query, classification)
            except Exception:
                slots = {}
        
        merged_slots = dict(self.session_slots)
        for k, v in slots.items():
            if v is not None:
                merged_slots[k] = v
        
        # Validate slots before proceeding
        try:
            ok, missing, invalid = validate_slots(template_key, merged_slots)
        except Exception:
            ok, missing, invalid = True, [], []
        
        if not ok:
            # Use follow-up generator to get a single question
            follow_up_data = self.follow_up_generator.generate_follow_up_question(
                query_info={"label": template_key},
                profile=merged_slots,
                lab_results=[],
                clarifications={}
            )
            
            if follow_up_data:
                self._awaiting_slot = follow_up_data["slot"]
                progress = self._get_progress_indicator(template_key, merged_slots)
                question_with_progress = follow_up_data["question"] + progress
                self._awaiting_question = question_with_progress

                return {
                    "template": "followup",
                    "answer": question_with_progress,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": "Awaiting required details",
                    "warnings": ["missing_data"],
                    "composer_placeholder": follow_up_data["composer_placeholder"]
                }
            else:
                # Fallback to craft_missing_slot_questions if generator fails
                qs = craft_missing_slot_questions(template_key, missing, invalid) or []
                next_q = qs[0] if qs else "Could you share the missing details (age, sex, diagnosis, allergies)?"
                self._awaiting_slot = missing[0] if missing else None
                self._awaiting_question = next_q
                
                return {
                    "template": "followup",
                    "answer": next_q,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": "Awaiting required details",
                    "warnings": ["missing_data"],
                    "composer_placeholder": next_q
                }
        
        # CRITICAL: Medication-first check for therapy intents
        if template_key in ["therapy", "dermatology"]:
            if not merged_slots.get("medications") or not isinstance(merged_slots["medications"], list) or len(merged_slots["medications"]) == 0:
                # Check if we've already asked about medications
                if not self._awaiting_slot or self._awaiting_slot != "medications":
                    self._awaiting_slot = "medications"
                    progress = self._get_progress_indicator(template_key, merged_slots)
                    question_with_progress = "Are you currently taking any medications? If yes, list them." + progress
                    self._awaiting_question = question_with_progress
                    return {
                        "template": "followup",
                        "answer": question_with_progress,
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Awaiting medication information",
                        "warnings": ["medication_required"],
                        "composer_placeholder": "List medications or type 'none'"
                    }
        
        # Build filters using the locked/current intent
        filter_candidates = build_filters(template_key, merged_slots)
        clarifications = None
        if filter_candidates.get("clarification_needed", False):
            options = filter_candidates.get("clarification_options", [])
            opts = ", ".join(options[:5]) if options else ""
            q = (
                f"Which country/region Food Composition Table should I use? Options: {opts}"
                if opts else "Which country/region Food Composition Table should I use?"
            )
            # Lock intent while waiting for user response
            self._intent_lock = template_key
            self._awaiting_slot = "country"
            self._awaiting_question = q
            return {
                "template": "followup",
                "answer": q,
                "followups": [],
                "model_used": "none",
                "therapy_output": None,
                "therapy_summary": None,
                "sources_used": [],
                "model_note": "Awaiting FCT selection",
                "warnings": ["needs_clarification"],
                "composer_placeholder": q
            }
        
        try:
            llm = get_llm_client(template_key)
        except Exception:
            llm = None
        
        system_prompt = build_prompt(template_key, merged_slots)
        sources = self._select_sources(template_key, subtype=merged_slots.get("subtype"), slots=merged_slots)
        combined_sources = list(set(filter_candidates.get("prioritized_sources", []) + sources))
        answer = "⚠️ No retriever or LLM available."
        warnings: List[str] = []
        citations: List[Dict[str, Any]] = []
        
        if retriever and self._should_use_fct(template_key, query, merged_slots):
            try:
                retrieved_docs = filtered_retrieval(query, filter_candidates.get("filters", {}), k=3, sources=combined_sources)
                # Allergy-aware filtering (remove foods matching user-declared allergies)
                allergies = [a.lower() for a in (merged_slots.get("allergies") or []) if isinstance(a, str)]
                allergies = [a for a in allergies if a not in ("none", "no allergies", "no allergy", "nil", "n/a")]
                if allergies and retrieved_docs:
                    filtered = []
                    for doc in retrieved_docs:
                        food_name = (doc.metadata or {}).get("food_name", "").lower()
                        if any(allergen in food_name for allergen in allergies):
                            continue
                        filtered.append(doc)
                    retrieved_docs = filtered
                
                # Build FCT-style citations if we have docs (flat items)
                for doc in (retrieved_docs or []):
                    meta = doc.metadata or {}
                    fct_item = {
                        "type": "fct",
                        "food": meta.get("food_name") or meta.get("food"),
                        "country_label": meta.get("country") or meta.get("country_table") or meta.get("table_country"),
                        "source": meta.get("source") or meta.get("country_table") or "Food Composition Tables",
                        "ref": None,
                    }
                    sid = meta.get("source_id") or meta.get("id") or None
                    page = meta.get("page") or meta.get("page_no") or None
                    if sid and page:
                        fct_item["ref"] = f"{sid}:{page}"
                    elif sid:
                        fct_item["ref"] = str(sid)
                    elif page:
                        fct_item["ref"] = str(page)
                    citations.append(fct_item)
                
                context = "\n".join([doc.page_content for doc in retrieved_docs]) if retrieved_docs else ""
                prompt = (
                    f"{system_prompt}\nContext:\n{context}\nUser: {query}"
                    if context
                    else f"{system_prompt}\nUser: {query}"
                )
                if not context:
                    warnings.append("fct_unavailable")
                    answer = "⚠️ FCT data unavailable — using USDA 2023 defaults"
                else:
                    answer = llm.invoke(prompt) if llm else "⚠️ FCT data unavailable — using USDA 2023 defaults"
            except Exception:
                warnings.append("fct_unavailable")
                answer = "⚠️ FCT data unavailable — using USDA 2023 defaults"
        elif llm:
            try:
                answer = llm.invoke(f"{system_prompt}\nUser: {query}")
            except Exception:
                answer = "Model offline — using defaults."
        
        therapy_output, therapy_summary = None, None
        if template_key in ["therapy", "recommendation", "dermatology"]:
            try:
                therapy_output = self._generate_diet_therapy(merged_slots)
                if therapy_output is None:
                    therapy_output = {}
                # Attach allergies for visibility in UI
                if merged_slots.get("allergies") is not None:
                    therapy_output["allergies"] = merged_slots.get("allergies")
                # Consent-based meal planning: only for therapy/dermatology
                if template_key in ["therapy", "dermatology"] and self._wants_meal_plan(query):
                    days = self._parse_meal_plan_days(query)
                    if days not in (1, 7):
                        return {
                            "template": "followup",
                            "answer": "Would you like a 1-day or 7-day meal plan? Please confirm with 'yes' or 'no'.",
                            "followups": [],
                            "model_used": "none",
                            "therapy_output": therapy_output,
                            "therapy_summary": None,
                            "sources_used": sources,
                            "citations": citations,
                            "llm_model_id": getattr(llm, "model_id", "unknown"),
                            "model_note": "Awaiting meal-plan consent",
                            "warnings": warnings + (["fct_unavailable"] if not retriever else []),
                            "composer_placeholder": "Would you like a 1-day or 7-day meal plan? Please confirm with 'yes' or 'no'."
                        }
                    # Only generate meal plan after explicit consent
                    if "yes" in query.lower() or "ok" in query.lower() or "sure" in query.lower():
                        self._meal_plan_consent = True
                        plan = self._build_meal_plan(merged_slots, days)
                        therapy_output.update(plan)
                        citations.extend(plan.get("citations", []))
                        if not plan.get("_fct_used"):
                            warnings.append("fct_unavailable")
                        answer = f"Generated a {days}-day meal plan. See Summary for meals and shopping list."
                    else:
                        # User said "no" or didn't confirm
                        self._meal_plan_consent = False
                        answer = "Meal plan generation cancelled. Let me know if you'd like to proceed later."
                therapy_summary = self._summarize_therapy_output(merged_slots, therapy_output)
            except Exception:
                therapy_output, therapy_summary = None, None
        
        followups = []
        # Derive model name more accurately
        try:
            provider_type = getattr(llm, "_llm_type", "unknown") if llm else "none"
            if provider_type == "together":
                model_name = "Together"
            elif "huggingface" in provider_type:
                model_name = "HuggingFace"
            else:
                model_name = provider_type
        except Exception:
            model_name = "unknown"
        
        for k in ("country", "age", "sex", "weight_kg", "height_cm", "allergies", "medications", "diagnosis"):
            if merged_slots.get(k) is not None:
                self.session_slots[k] = merged_slots[k]
        
        # Clean up any garbled unicode artifacts that may appear in strings
        def _clean_text(s: Optional[str]) -> Optional[str]:
            if not isinstance(s, str):
                return s
            out = s.replace(" ?T", "'").replace(" ", "").replace('""', '"')
            out = out.replace(" don?t ", " don't ")
            return out
        
        answer = _clean_text(answer)
        if isinstance(answer, str) and ("LLM failed" in answer or "No LLM available" in answer):
            answer = "Model offline — using defaults."
        
        if therapy_summary:
            therapy_summary = _clean_text(therapy_summary)
        
        # Append explicit allergy-aware note to the answer when applicable
        try:
            allergy_items = []
            if isinstance(merged_slots.get("allergies"), list):
                allergy_items = [
                    a for a in [str(x).strip().lower() for x in merged_slots.get("allergies")]
                    if a and a not in ("none", "no allergy", "no allergies", "nil", "n/a")
                ]
            if allergy_items and isinstance(answer, str):
                note = f"Allergy-aware: excluded {', '.join(sorted(set(allergy_items)))}."
                answer = f"{answer}\n{note}"
        except Exception:
            pass
        
        # If an optimized diet plan exists, ensure allergenic foods are removed as a final guard
        try:
            if therapy_output and isinstance(therapy_output.get("optimized_plan", {}), dict):
                diet = therapy_output["optimized_plan"].get("diet_plan", [])
                allerg_set = set(
                    a for a in [
                        str(x).strip().lower() for x in (merged_slots.get("allergies") or [])
                    ] if a and a not in ("none", "no allergy", "no allergies", "nil", "n/a")
                )
                if allerg_set and isinstance(diet, list):
                    filtered_diet = [
                        item for item in diet
                        if not any(allergen in str(item.get("food", "")).lower() for allergen in allerg_set)
                    ]
                    therapy_output["optimized_plan"]["diet_plan"] = filtered_diet
        except Exception:
            pass
        
        # Add guideline/book citations with publication years (flat items)
        try:
            import re
            for s in (sources or []):
                if isinstance(s, str):
                    if s.lower().strip() in ("food composition tables",):
                        continue
                    # Better year extraction - store during PDF indexing, not string parsing
                    # For now, we'll assume year is stored in metadata
                    year = None
                    if "2024" in s:
                        year = "2024"
                    elif "2023" in s:
                        year = "2023"
                    elif "2022" in s:
                        year = "2022"
                    elif "2021" in s:
                        year = "2021"
                    elif "2020" in s:
                        year = "2020"
                    citations.append({"type": "guideline", "title": s, "year": year})
        except Exception:
            pass
        
        # Deduplicate citations (simple seen set by tuple signature)
        try:
            seen = set()
            deduped = []
            for c in citations:
                key = (
                    c.get("type"),
                    c.get("food"),
                    c.get("country_label"),
                    c.get("source"),
                    c.get("ref"),
                    c.get("title"),
                    c.get("year"),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(c)
            citations = deduped
        except Exception:
            pass
        
        # Model transparency note
        try:
            provider = getattr(llm, "_llm_type", "none") if llm else "none"
            model_id_note = getattr(llm, "model_name", None) or getattr(llm, "repo_id", None) or "unknown"
            model_note = f"Using {model_id_note} ({'Together' if provider=='together' else 'HF' if 'huggingface' in provider else provider})"
        except Exception:
            model_note = None
        
        # CRITICAL: Add medical disclaimer to EVERY response
        disclaimer = "For educational purposes only. Not medical advice. Consult a healthcare provider."
        if disclaimer not in answer:
            if isinstance(answer, str):
                answer = f"{disclaimer}\n{answer}"
            else:
                answer = f"{disclaimer}\n{str(answer)}"
        
        # CRITICAL: Central safety validation layer
        safety_ok, safety_message = self._validate_response_safety(answer, merged_slots)
        if not safety_ok:
            logger.error(f"❌ Safety check failed: {safety_message}")
            return {
                "template": "safety_failure",
                "answer": "⚠️ Safety check failed. This response contains potential clinical risks. Please try again or contact support.",
                "followups": [],
                "model_used": "none",
                "therapy_output": None,
                "therapy_summary": None,
                "sources_used": [],
                "citations": [],
                "llm_model_id": "none",
                "model_note": "Safety failure",
                "warnings": ["safety_failure"],
                "composer_placeholder": "Safety check failed. Please try again or contact support."
            }
        
        return {
            "template": template_key,
            "answer": answer,
            "followups": followups,
            "model_used": model_name,
            "therapy_output": therapy_output,
            "therapy_summary": therapy_summary,
            "sources_used": sources,
            "citations": citations,
            "llm_model_id": getattr(llm, "model_id", model_name),
            "model_note": model_note,
            "warnings": warnings,
            "composer_placeholder": self._awaiting_question or ""
        }