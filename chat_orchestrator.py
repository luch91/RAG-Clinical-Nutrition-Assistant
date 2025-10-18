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
from app.components.query_classifier import NutritionQueryClassifier, BIOMARKERS
from app.components.api_models import get_llm_client
from app.components.hybrid_retriever import filtered_retrieval, retriever
from app.components.nutrient_calculator import optimize_diet, meal_planner, convert_fct_rows_to_foods
from app.common.logger import get_logger
# Day 1 & Day 2
from app.common.slot_extractor import extract_slots_from_query
# PHASE 4 CLEANUP: validate_slots removed - step-by-step collector handles validation
from app.common.retrieval_filters import build_filters
# Day 3
from app.common.templates import build_prompt
# Follow-up generator
from app.components.followup_question_generator import FollowUpQuestionGenerator
# Step-by-step collector
from app.components.step_by_step_collector import StepByStepTherapyCollector

logger = get_logger(__name__)

# ---------------------------
# Supported Therapy Conditions (Official List - NEVER FORGET)
# ---------------------------
SUPPORTED_THERAPY_CONDITIONS = [
    # Preterm Nutrition
    "preterm", "premature", "nicu", "low birth weight", "preemie",

    # Type 1 Diabetes
    "type 1 diabetes", "t1d", "diabetes type 1", "insulin dependent diabetes", "iddm",

    # Food Allergy
    "food allergy", "food allergies", "allergic", "anaphylaxis",

    # Cystic Fibrosis
    "cystic fibrosis", "cf", "cftr",

    # Inherited Metabolic Disorders
    "pku", "phenylketonuria",
    "msud", "maple syrup urine disease",
    "galactosemia",
    "iem", "inborn error", "metabolic disorder",

    # Epilepsy / Ketogenic Therapy
    "epilepsy", "seizure", "seizures", "ketogenic", "keto diet", "keto therapy",

    # Chronic Kidney Disease
    "ckd", "chronic kidney disease", "renal disease", "kidney disease", "renal failure",

    # GI Disorders (IBD / GERD)
    "ibd", "inflammatory bowel",
    "crohn", "crohn's", "crohn's disease",
    "ulcerative colitis", "uc",
    "gerd", "reflux", "gastroesophageal reflux"
]

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

def is_therapy_supported(diagnosis: str) -> bool:
    """
    Check if diagnosis is in the supported therapy list.

    Official therapy support conditions:
    1. Preterm Nutrition
    2. Type 1 Diabetes
    3. Food Allergy
    4. Cystic Fibrosis
    5. Inherited Metabolic Disorders (PKU, MSUD, Galactosemia)
    6. Epilepsy / Ketogenic Therapy
    7. Chronic Kidney Disease
    8. GI Disorders (IBD / GERD)

    Returns:
        True if diagnosis matches any supported condition, False otherwise
    """
    if not diagnosis:
        return False

    diagnosis_lower = diagnosis.lower()
    return any(condition in diagnosis_lower for condition in SUPPORTED_THERAPY_CONDITIONS)


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
        # Step-by-step therapy collector (dedicated state machine)
        self._step_by_step_collector: Optional[StepByStepTherapyCollector] = None
    
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
        self._step_by_step_collector = None  # Clear step-by-step collector
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
                        # Handle score as both string and number
                        score_raw = best_match.get("score", 0)
                        try:
                            confidence = float(score_raw) / 100.0
                        except (ValueError, TypeError):
                            confidence = 0.0
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
    # Rejection handler (graceful degradation)
    # ---------------------------
    def _handle_slot_rejection(self, slot: str, rejection_reason: str, classification: dict, merged_slots: Dict[str, Any]) -> dict:
        """
        Handle when user can't/won't provide required slot.
        Implements graceful degradation with alternatives.

        Args:
            slot: The slot that was rejected (e.g., "biomarkers", "medications", "age")
            rejection_reason: Why it was rejected ("user_rejected", "not_available", etc.)
            classification: The classification result from query_classifier
            merged_slots: Current session slots

        Returns:
            Dict response with graceful degradation options
        """
        # Critical slots for therapy (medications + biomarkers)
        if slot in ["medications", "biomarkers"] or slot in BIOMARKERS:
            diagnosis = merged_slots.get("diagnosis", "your condition")

            if rejection_reason == "user_rejected":
                # User explicitly said "no" or "don't have"
                if slot == "medications":
                    message = (
                        f"I understand you're not currently on medications. "
                        f"I can provide general nutritional recommendations for {diagnosis}, "
                        f"but personalized therapy requires medication information.\n\n"
                        f"Would you like:\n"
                        f"1. General nutritional recommendations (no medications needed)\n"
                        f"2. Wait - I'll get my medication list and come back\n\n"
                        f"Type '1' for general recommendations or '2' to get medications first."
                    )
                else:  # biomarkers
                    message = (
                        f"I understand lab results aren't available. "
                        f"Without biomarker data (HbA1c, creatinine, eGFR, etc.), I can provide "
                        f"general nutritional recommendations for {diagnosis}, but NOT personalized therapy.\n\n"
                        f"Would you like:\n"
                        f"1. General nutritional recommendations (no labs needed)\n"
                        f"2. Upload lab results if you have them (photo/PDF)\n"
                        f"3. Wait - I'll get my lab results and come back\n\n"
                        f"Type '1', '2', or '3'."
                    )

                # Clear the awaiting slot and downgrade intent to recommendation
                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0

                return {
                    "template": "followup",
                    "answer": message,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": f"Rejected slot: {slot}",
                    "warnings": ["slot_rejected", "downgrade_to_recommendation"],
                    "composer_placeholder": "Choose 1, 2, or 3"
                }

        # Non-critical slots (age, weight, height, country)
        elif slot in ["age", "weight_kg", "height_cm", "sex", "country"]:
            if rejection_reason == "user_rejected":
                message = (
                    f"No problem. I'll use typical age-based defaults for {slot.replace('_', ' ')}. "
                    f"The recommendations may be less personalized, but I'll still provide helpful guidance."
                )

                # Set default value based on slot type
                default_values = {
                    "age": 30,  # Adult default
                    "weight_kg": 70,
                    "height_cm": 170,
                    "sex": "unknown",
                    "country": "Nigeria"  # Default to Nigeria (primary FCT)
                }

                if slot in default_values:
                    merged_slots[slot] = default_values[slot]
                    self.session_slots[slot] = default_values[slot]

                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0

                return {
                    "template": "followup",
                    "answer": message,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": f"Using default for {slot}",
                    "warnings": ["using_defaults"],
                    "composer_placeholder": ""
                }

        # Allergies (can be "none")
        elif slot == "allergies":
            merged_slots[slot] = ["none"]
            self.session_slots[slot] = ["none"]
            self._awaiting_slot = None
            self._awaiting_question = None
            self._retry_count = 0
            # DON'T return early - let code fall through to generate therapy
            logger.info("✅ Allergies processed - continuing to therapy generation")

        # Diagnosis (critical for therapy)
        elif slot == "diagnosis":
            if rejection_reason == "user_rejected":
                message = (
                    "A diagnosis helps me provide more targeted recommendations. "
                    "Without it, I can only offer very general nutritional guidance. "
                    "Would you like to:\n"
                    "1. Provide a general health goal instead (e.g., 'improve energy', 'weight management')\n"
                    "2. Continue with general nutrition recommendations\n\n"
                    "Type '1' or '2'."
                )

                return {
                    "template": "followup",
                    "answer": message,
                    "followups": [],
                    "model_used": "none",
                    "therapy_output": None,
                    "therapy_summary": None,
                    "sources_used": [],
                    "model_note": "Diagnosis rejected",
                    "warnings": ["missing_diagnosis"],
                    "composer_placeholder": "Choose 1 or 2"
                }

        # Fallback for any other slots
        else:
            self._awaiting_slot = None
            self._awaiting_question = None
            self._retry_count = 0

            return {
                "template": "followup",
                "answer": f"Understood. Continuing without {slot.replace('_', ' ')}...",
                "followups": [],
                "model_used": "none",
                "therapy_output": None,
                "therapy_summary": None,
                "sources_used": [],
                "model_note": f"Skipped slot: {slot}",
                "warnings": ["slot_skipped"],
                "composer_placeholder": ""
            }

    # ---------------------------
    # Therapy onboarding flow
    # ---------------------------
    def _therapy_onboarding_flow(
        self,
        diagnosis: str,
        missing_meds: bool,
        missing_biomarkers: bool,
        missing_age: bool,
        missing_weight: bool,
        query: str
    ) -> Dict[str, Any]:
        """
        Onboarding flow for users who explicitly request therapy but lack data.
        Instead of silent downgrade, educate and guide data collection.
        """

        # Build list of missing items
        missing_items = []
        if missing_age:
            missing_items.append("❌ Patient age (for age-appropriate requirements)")
        if missing_meds:
            missing_items.append("❌ Current medications (for drug-nutrient interactions)")
        if missing_biomarkers:
            missing_items.append("❌ Recent lab results (creatinine, eGFR, electrolytes)")
        if missing_weight:
            missing_items.append("❌ Weight & height (for calorie calculations)")

        missing_items_text = "\n".join(missing_items)

        # Get diagnosis-specific biomarkers
        diagnosis_biomarkers = self._get_diagnosis_specific_biomarkers(diagnosis)

        # Format response
        answer = f"""🎯 **{diagnosis or 'Pediatric'} Diet Therapy - Let's Get Started!**

I can create a **personalized therapy plan** for {diagnosis or 'this condition'}, but I need clinical information first. This ensures safe, evidence-based recommendations.

**Required Information:**
{missing_items_text}

**Optional but Helpful:**
• Country/region (for food availability)
• Food allergies or intolerances
{f'• {diagnosis} stage (if known)' if diagnosis and diagnosis.upper() in ['CKD', 'Cirrhosis'] else ''}

{f'''**Key Lab Values for {diagnosis}:**
{diagnosis_biomarkers}
''' if diagnosis_biomarkers else ''}

---

**How would you like to proceed?**

📋 **Option 1: Upload Lab Results** (Fastest)
   Upload a PDF or photo of recent lab report. I'll extract biomarker values automatically.
   → Click [Upload Lab Results] button below ↓

✍️ **Option 2: Answer Step-by-Step** ({len(missing_items)} questions)
   I'll ask one question at a time (age, medications, labs, etc.)
   Takes 2-3 minutes.
   → Type "step by step"

📚 **Option 3: General {diagnosis or 'Diet'} Information First**
   Get general diet guidelines for {diagnosis or 'this condition'} while you gather clinical data, then come back for personalized therapy.
   → Type "general info first"

Which option works best for you?

---
_⚠️ For educational purposes only. Not medical advice. Consult a healthcare provider._
"""

        # CRITICAL: Set self._awaiting_slot so next turn triggers the handler
        self._awaiting_slot = "data_collection_method"
        self._awaiting_question = "Choose data collection method"
        self._intent_lock = "therapy"  # Lock to therapy intent

        return {
            "template": "followup",
            "answer": answer,
            "followups": [],
            "model_used": "none",
            "therapy_output": None,
            "therapy_summary": None,
            "sources_used": [],
            "citations": [],
            "model_note": "Therapy onboarding - awaiting data collection method",
            "warnings": ["therapy_onboarding", "missing_clinical_data"],
            "composer_placeholder": "Choose: upload / step by step / general info first",
            "quick_actions": ["Upload Lab Results", "Step by Step", "General Info First"],
            "highlight_upload_button": True,
            "awaiting_slot": "data_collection_method",
            "classification": {
                "label": "therapy_pending",
                "original_label": "therapy",
                "diagnosis": diagnosis,
                "missing_items": missing_items
            }
        }

    def _get_diagnosis_specific_biomarkers(self, diagnosis: str) -> str:
        """Return key biomarkers for specific diagnosis"""

        if not diagnosis:
            return ""

        diagnosis_lower = diagnosis.lower()

        biomarker_map = {
            "ckd": "Creatinine, eGFR, Potassium, Phosphate, Calcium, Albumin",
            "chronic kidney disease": "Creatinine, eGFR, Potassium, Phosphate, Calcium, Albumin",
            "renal": "Creatinine, eGFR, Potassium, Phosphate, Calcium, Albumin",
            "t1d": "HbA1c, Fasting Glucose, C-peptide (if available)",
            "type 1 diabetes": "HbA1c, Fasting Glucose, C-peptide (if available)",
            "diabetes": "HbA1c, Fasting Glucose, C-peptide (if available)",
            "epilepsy": "Drug levels (if on AEDs), Vitamin D, Folate, B12",
            "cf": "Vitamins A/D/E/K, Albumin, Prealbumin",
            "cystic fibrosis": "Vitamins A/D/E/K, Albumin, Prealbumin",
            "iem": "Depends on specific IEM - Amino acids, Organic acids",
            "inborn error": "Depends on specific IEM - Amino acids, Organic acids",
            "cirrhosis": "Albumin, Bilirubin, PT/INR, Ammonia",
            "food allergy": "IgE levels (if known), Eosinophil count",
            "allergy": "IgE levels (if known), Eosinophil count",
            "preterm": "Albumin, Calcium, Phosphate, ALP, Weight gain"
        }

        for key, biomarkers in biomarker_map.items():
            if key in diagnosis_lower:
                return biomarkers

        return ""

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
    # OPTION A + B: Enhanced Therapy Generation with Biomarkers + LLM
    # ---------------------------
    def _generate_diet_therapy(self, slots: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate personalized nutrition therapy using:
        - Option A: Enhanced formulas with diagnosis-specific biomarker logic
        - Option B: LLM-powered therapy generation with RAG retrieval

        Returns structure compatible with Therapy Summary renderer.
        """
        # Extract demographics
        age = slots.get("age")
        sex = (slots.get("sex") or "").lower()
        weight = slots.get("weight_kg") or slots.get("weight")
        height = slots.get("height_cm") or slots.get("height")
        diagnosis = slots.get("diagnosis", "").lower()

        try:
            age_val = int(age) if age is not None else None
        except Exception:
            age_val = None

        is_adult = (age_val is None) or (age_val >= 18)

        # Default values if missing
        if weight is None:
            weight = 60 if sex == "female" else 70 if is_adult else 30
        if height is None:
            height = 165 if sex == "female" else 175 if is_adult else 130

        try:
            w = float(weight)
            h = float(height)
        except Exception:
            w = weight
            h = height

        # OPTION A: Diagnosis-Specific Biomarker-Driven Targets
        targets = self._calculate_diagnosis_specific_targets(
            diagnosis=diagnosis,
            age_val=age_val,
            weight=w,
            height=h,
            sex=sex,
            is_adult=is_adult,
            slots=slots
        )

        # OPTION B: LLM-Powered Therapy Enhancement
        llm_therapy_guidance = self._generate_llm_therapy_guidance(
            diagnosis=diagnosis,
            slots=slots,
            targets=targets
        )

        # Combine both approaches
        therapy_output: Dict[str, Any] = {
            "nutrient_targets": targets,
            "biochemical_rationale": self._biochemical_rationale(slots, targets),
            "drug_nutrient_interactions": [],
            "optimized_plan": {},
            "llm_guidance": llm_therapy_guidance  # From Option B
        }

        return therapy_output

    def _calculate_diagnosis_specific_targets(
        self,
        diagnosis: str,
        age_val: Optional[int],
        weight: float,
        height: float,
        sex: str,
        is_adult: bool,
        slots: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        OPTION A: Calculate nutrient targets based on diagnosis and biomarkers.
        Implements diagnosis-specific logic for all 8 supported conditions.
        """
        # Base calculations
        energy_kcal = 2000 if is_adult else 1400
        protein_g = max(45, round(0.8 * weight)) if is_adult else max(30, round(1.0 * weight))

        # Initialize targets
        targets = {
            "energy_kcal": energy_kcal,
            "macros": {"protein_g": protein_g, "carb_g": 250, "fat_g": 65},
            "micros": {}
        }

        # 1. TYPE 1 DIABETES
        if "diabet" in diagnosis or "t1d" in diagnosis or "iddm" in diagnosis:
            hba1c = slots.get("hba1c")
            glucose = slots.get("glucose")

            # Adjust carb targets based on HbA1c control
            if hba1c:
                if hba1c > 8.0:
                    # Poor control - tighter carb restriction
                    targets["macros"]["carb_g"] = 150
                    targets["micros"]["fiber_g"] = 30  # High fiber for glycemic control
                elif hba1c > 7.0:
                    # Moderate control
                    targets["macros"]["carb_g"] = 180
                    targets["micros"]["fiber_g"] = 25
                else:
                    # Good control
                    targets["macros"]["carb_g"] = 200
                    targets["micros"]["fiber_g"] = 25

            # Micronutrients for diabetes
            targets["micros"]["chromium_mcg"] = 200
            targets["micros"]["magnesium_mg"] = 400
            targets["micros"]["vitamin_d_iu"] = 2000

        # 2. CHRONIC KIDNEY DISEASE (CKD)
        elif "ckd" in diagnosis or "kidney" in diagnosis or "renal" in diagnosis:
            egfr = slots.get("egfr")
            creatinine = slots.get("creatinine")
            potassium = slots.get("potassium")
            phosphorus = slots.get("phosphorus")

            # Adjust protein based on CKD stage (eGFR)
            if egfr:
                if egfr < 15:
                    # Stage 5 (dialysis)
                    targets["macros"]["protein_g"] = round(1.2 * weight) if is_adult else round(1.5 * weight)
                elif egfr < 30:
                    # Stage 4
                    targets["macros"]["protein_g"] = round(0.6 * weight) if is_adult else round(0.8 * weight)
                elif egfr < 60:
                    # Stage 3
                    targets["macros"]["protein_g"] = round(0.8 * weight) if is_adult else round(1.0 * weight)

            # Mineral restrictions based on biomarkers
            if potassium and potassium > 5.0:
                targets["micros"]["potassium_mg"] = 2000  # Restrict
            else:
                targets["micros"]["potassium_mg"] = 3000

            if phosphorus and phosphorus > 4.5:
                targets["micros"]["phosphorus_mg"] = 800  # Restrict
            else:
                targets["micros"]["phosphorus_mg"] = 1200

            # Always restrict sodium in CKD
            targets["micros"]["sodium_mg"] = 2000
            targets["micros"]["calcium_mg"] = 1000

        # 3. EPILEPSY / KETOGENIC THERAPY
        elif "epilep" in diagnosis or "seizure" in diagnosis or "ketogenic" in diagnosis or "keto" in diagnosis:
            ketone_level = slots.get("ketone_level")
            seizure_frequency = slots.get("seizure_frequency")

            # Ketogenic ratio calculations
            if "ketogenic" in diagnosis.lower() or ketone_level:
                # Classic ketogenic diet: 4:1 or 3:1 ratio (fat:protein+carb)
                targets["energy_kcal"] = round(energy_kcal * 1.2)  # Higher energy from fat
                targets["macros"]["fat_g"] = round(weight * 3.5)  # High fat
                targets["macros"]["carb_g"] = 20  # Very low carb
                targets["macros"]["protein_g"] = round(weight * 1.0)

            # Micronutrients for epilepsy
            targets["micros"]["vitamin_d_iu"] = 2000
            targets["micros"]["calcium_mg"] = 1300
            targets["micros"]["selenium_mcg"] = 70

        # 4. CYSTIC FIBROSIS (CF)
        elif "cystic fibrosis" in diagnosis or "cf" in diagnosis or "cftr" in diagnosis:
            fev1 = slots.get("fev1")
            pancreatic_status = slots.get("pancreatic_status")

            # High-calorie, high-fat diet
            targets["energy_kcal"] = round(energy_kcal * 1.5)  # 150% of normal
            targets["macros"]["protein_g"] = round(weight * 1.5)  # Higher protein
            targets["macros"]["fat_g"] = round(weight * 2.0)  # High fat

            # Fat-soluble vitamins (CF patients often deficient)
            targets["micros"]["vitamin_a_iu"] = 10000
            targets["micros"]["vitamin_d_iu"] = 2000
            targets["micros"]["vitamin_e_iu"] = 400
            targets["micros"]["vitamin_k_mcg"] = 120
            targets["micros"]["sodium_mg"] = 3000  # Liberal sodium (sweat losses)

        # 5. INHERITED METABOLIC DISORDERS (IEMs)
        elif any(term in diagnosis for term in ["pku", "phenylketonuria", "msud", "maple syrup", "galactosemia", "metabolic disorder", "inborn error"]):
            # PKU
            if "pku" in diagnosis or "phenylketonuria" in diagnosis:
                phenylalanine = slots.get("phenylalanine")

                if phenylalanine:
                    if phenylalanine > 10:
                        # High phe - strict restriction
                        targets["macros"]["protein_g"] = round(weight * 0.5)  # Low natural protein
                        targets["micros"]["phenylalanine_mg"] = 300  # Strict limit
                    elif phenylalanine > 6:
                        targets["macros"]["protein_g"] = round(weight * 0.7)
                        targets["micros"]["phenylalanine_mg"] = 500
                    else:
                        targets["macros"]["protein_g"] = round(weight * 1.0)
                        targets["micros"]["phenylalanine_mg"] = 700

                targets["micros"]["tyrosine_mg"] = 4000  # Supplemental tyrosine

            # MSUD
            elif "msud" in diagnosis or "maple syrup" in diagnosis:
                leucine = slots.get("leucine")

                # Restrict branched-chain amino acids
                targets["macros"]["protein_g"] = round(weight * 0.7)
                targets["micros"]["leucine_mg"] = 500  # Strict limit
                targets["micros"]["isoleucine_mg"] = 300
                targets["micros"]["valine_mg"] = 350

            # Galactosemia
            elif "galactosemia" in diagnosis:
                # Strict galactose/lactose restriction
                targets["macros"]["carb_g"] = 200
                targets["micros"]["calcium_mg"] = 1300  # Compensate for no dairy
                targets["micros"]["vitamin_d_iu"] = 2000

        # 6. PRETERM NUTRITION
        elif "preterm" in diagnosis or "premature" in diagnosis or "nicu" in diagnosis or "preemie" in diagnosis:
            gestational_age = slots.get("gestational_age")
            corrected_age = slots.get("corrected_age")

            # Aggressive nutrition for catch-up growth
            targets["energy_kcal"] = round(120 * weight)  # kcal/kg/day
            targets["macros"]["protein_g"] = round(3.5 * weight)  # g/kg/day
            targets["macros"]["fat_g"] = round(6 * weight)  # High fat for brain development

            # Critical micronutrients for preterm
            targets["micros"]["iron_mg"] = 4  # High iron needs
            targets["micros"]["calcium_mg"] = 200  # mg/kg/day
            targets["micros"]["phosphorus_mg"] = 120
            targets["micros"]["vitamin_d_iu"] = 400

        # 7. FOOD ALLERGY
        elif "food allerg" in diagnosis or "allergic" in diagnosis or "anaphylaxis" in diagnosis:
            allergen_type = slots.get("allergen_type")
            ige_level = slots.get("ige_level")

            # Ensure adequate nutrition despite exclusions
            targets["macros"]["protein_g"] = round(weight * 1.2)  # Compensate for restrictions
            targets["micros"]["calcium_mg"] = 1300  # If dairy allergy
            targets["micros"]["vitamin_d_iu"] = 2000
            targets["micros"]["omega3_mg"] = 1000  # Anti-inflammatory

        # 8. GI DISORDERS (IBD, GERD, Crohn's, UC)
        elif any(term in diagnosis for term in ["ibd", "crohn", "ulcerative colitis", "gerd", "reflux", "inflammatory bowel"]):
            crp = slots.get("crp")
            esr = slots.get("esr")
            fecal_calprotectin = slots.get("fecal_calprotectin")
            albumin = slots.get("albumin")

            # Anti-inflammatory, easily digestible diet
            targets["energy_kcal"] = round(energy_kcal * 1.3)  # Higher energy needs
            targets["macros"]["protein_g"] = round(weight * 1.5)  # High protein for healing
            targets["macros"]["fat_g"] = round(weight * 1.0)  # Moderate fat

            # Micronutrients for IBD
            targets["micros"]["vitamin_d_iu"] = 2000
            targets["micros"]["vitamin_b12_mcg"] = 100
            targets["micros"]["folate_mcg"] = 800
            targets["micros"]["iron_mg"] = 27  # Often deficient
            targets["micros"]["zinc_mg"] = 25
            targets["micros"]["omega3_mg"] = 2000  # Anti-inflammatory

        return targets

    def _generate_llm_therapy_guidance(
        self,
        diagnosis: str,
        slots: Dict[str, Any],
        targets: Dict[str, Any]
    ) -> str:
        """
        OPTION B: Generate LLM-powered therapy guidance using DeepSeek + RAG.
        Provides clinical reasoning and food recommendations.
        """
        if not diagnosis:
            return ""

        try:
            # Build biomarkers summary
            biomarkers_text = self._format_biomarkers_for_llm(slots)

            # Retrieve therapy guidelines from RAG (if available)
            guidelines_context = ""
            try:
                therapy_docs = filtered_retrieval(
                    f"Diet therapy guidelines for {diagnosis}",
                    {},  # Empty filters dict (positional arg)
                    k=5,
                    sources=["Clinical Nutrition", "Guidelines", "Clinical Paediatric Dietetics"]
                )
                guidelines_context = "\n".join([doc.page_content for doc in (therapy_docs or [])]) if therapy_docs else ""
            except Exception as retrieval_error:
                logger.debug(f"RAG retrieval skipped (retriever not initialized): {retrieval_error}")
                # Continue without RAG context - LLM can still provide guidance

            # Build prompt for DeepSeek
            prompt = f"""You are a clinical nutrition expert. Generate a concise therapy guidance for:

**Diagnosis:** {diagnosis}
**Age:** {slots.get('age', 'Not specified')} years
**Weight:** {slots.get('weight_kg', 'Not specified')} kg
**Medications:** {', '.join(slots.get('medications', [])) if slots.get('medications') else 'None'}

**Biomarkers:**
{biomarkers_text}

**Calculated Nutrient Targets:**
- Energy: {targets.get('energy_kcal')} kcal/day
- Protein: {targets.get('macros', {}).get('protein_g')} g/day
- Carbs: {targets.get('macros', {}).get('carb_g')} g/day
- Fat: {targets.get('macros', {}).get('fat_g')} g/day

**Clinical Guidelines Context:**
{guidelines_context[:1000] if guidelines_context else 'Using evidence-based clinical nutrition principles'}

Provide:
1. Brief rationale for these targets based on diagnosis and biomarkers
2. Top 5 food recommendations specific to this condition
3. Foods to avoid or limit
4. One key monitoring parameter

Keep response under 300 words, clinical and evidence-based."""

            # Call DeepSeek model
            try:
                llm = get_llm_client("therapy")  # Uses DeepSeek for therapy intent
                guidance = llm.invoke(prompt)
                return guidance if isinstance(guidance, str) else str(guidance)
            except Exception as llm_error:
                logger.debug(f"LLM call skipped: {llm_error}")
                return ""

        except Exception as e:
            logger.warning(f"LLM therapy guidance generation failed: {str(e)}")
            return ""

    def _format_biomarkers_for_llm(self, slots: Dict[str, Any]) -> str:
        """Format biomarkers from slots into readable text for LLM"""
        biomarkers = []

        # Type 1 Diabetes
        if slots.get("hba1c"):
            biomarkers.append(f"HbA1c: {slots['hba1c']}%")
        if slots.get("glucose"):
            biomarkers.append(f"Fasting Glucose: {slots['glucose']} mg/dL")

        # CKD
        if slots.get("creatinine"):
            biomarkers.append(f"Creatinine: {slots['creatinine']} mg/dL")
        if slots.get("egfr"):
            biomarkers.append(f"eGFR: {slots['egfr']} mL/min/1.73m²")
        if slots.get("potassium"):
            biomarkers.append(f"Potassium: {slots['potassium']} mEq/L")
        if slots.get("phosphorus"):
            biomarkers.append(f"Phosphorus: {slots['phosphorus']} mg/dL")

        # Epilepsy
        if slots.get("ketone_level"):
            biomarkers.append(f"Blood Ketones: {slots['ketone_level']} mmol/L")
        if slots.get("seizure_frequency"):
            biomarkers.append(f"Seizure Frequency: {slots['seizure_frequency']}/month")

        # CF
        if slots.get("fev1"):
            biomarkers.append(f"FEV1: {slots['fev1']}%")
        if slots.get("vitamin_d"):
            biomarkers.append(f"Vitamin D: {slots['vitamin_d']} ng/mL")

        # IEMs
        if slots.get("phenylalanine"):
            biomarkers.append(f"Phenylalanine: {slots['phenylalanine']} mg/dL")
        if slots.get("leucine"):
            biomarkers.append(f"Leucine: {slots['leucine']} µmol/L")

        # Preterm
        if slots.get("gestational_age"):
            biomarkers.append(f"Gestational Age: {slots['gestational_age']} weeks")
        if slots.get("hemoglobin"):
            biomarkers.append(f"Hemoglobin: {slots['hemoglobin']} g/dL")

        # IBD
        if slots.get("crp"):
            biomarkers.append(f"CRP: {slots['crp']} mg/L")
        if slots.get("albumin"):
            biomarkers.append(f"Albumin: {slots['albumin']} g/dL")

        return "\n".join(biomarkers) if biomarkers else "No biomarkers provided"
    
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
        slots = {}  # Initialize slots early to avoid UnboundLocalError

        if self._awaiting_slot and self._intent_lock:
            template_key = self._intent_lock
        else:
            pre_key = self._pre_classify(query)
            try:
                classification = self.classifier.classify(query)
            except Exception:
                classification = {"label": "general"}

            # Extract slots from classification early (before therapy gatekeeper needs them)
            try:
                slots = extract_slots_from_query(query, classification)
            except Exception:
                slots = {}

            # CRITICAL: Add diagnosis from classification to slots
            if classification.get("diagnosis"):
                slots["diagnosis"] = classification.get("diagnosis")
                # Also store in session_slots immediately so it's available for collector
                self.session_slots["diagnosis"] = classification.get("diagnosis")

            # CRITICAL: ENHANCED THERAPY GATEKEEPER with Onboarding
            if classification.get("label") == "therapy":
                medications = classification.get("medications", [])
                biomarkers = classification.get("biomarkers", [])

                # Check if user EXPLICITLY requested therapy
                explicit_therapy_keywords = [
                    "therapy", "treatment plan", "meal plan", "diet plan",
                    "personalized", "specific plan", "calculate", "requirements",
                    "need diet", "need meal", "nutrition therapy"
                ]
                user_explicitly_wants_therapy = any(
                    keyword in query.lower()
                    for keyword in explicit_therapy_keywords
                )

                # Merge with session slots to check total missing
                temp_merged = dict(self.session_slots)
                for k, v in slots.items():
                    if v is not None:
                        temp_merged[k] = v

                missing_meds = not medications or len(medications) == 0
                missing_biomarkers = not biomarkers or len(biomarkers) == 0
                missing_age = not temp_merged.get("age")
                missing_weight = not temp_merged.get("weight_kg")

                critical_missing_count = sum([missing_meds, missing_biomarkers, missing_age, missing_weight])

                if critical_missing_count == 0:
                    # ALL DATA PRESENT - Proceed with therapy!
                    logger.info(f"✅ Therapy gatekeeper passed: {len(medications)} medications, {len(biomarkers)} biomarkers")

                elif critical_missing_count >= 2 and user_explicitly_wants_therapy:
                    # USER EXPLICITLY WANTS THERAPY but missing 2+ critical slots
                    # → Don't silently downgrade, ONBOARD them!
                    logger.info("🎯 Therapy onboarding triggered: user wants therapy but missing data")
                    return self._therapy_onboarding_flow(
                        diagnosis=temp_merged.get("diagnosis"),
                        missing_meds=missing_meds,
                        missing_biomarkers=missing_biomarkers,
                        missing_age=missing_age,
                        missing_weight=missing_weight,
                        query=query
                    )

                elif critical_missing_count >= 2 and not user_explicitly_wants_therapy:
                    # Therapy intent detected but user didn't explicitly ask for it
                    # → Silently downgrade (old behavior)
                    logger.warning("⚠️ Therapy downgraded: missing critical data, user didn't explicitly request")
                    classification["label"] = "recommendation"
                    classification["downgrade_reason"] = "missing_critical_data"
                    classification["original_label"] = "therapy"

                elif missing_meds and not missing_biomarkers:
                    # Only medications missing - quick ask
                    logger.info("Therapy gatekeeper: missing medications only")
                    # Will be handled by standard follow-up flow

                elif missing_biomarkers and not missing_meds:
                    # Only biomarkers missing - nudge upload
                    logger.info("Therapy gatekeeper: missing biomarkers only")
                    # Will be handled by standard follow-up flow

                else:
                    # Missing only 1 critical slot or both present
                    logger.info(f"✅ Therapy gatekeeper passed: {len(medications)} medications, {len(biomarkers)} biomarkers")

            template_key = pre_key or classification.get("label", "general")
            # On first turn, lock the intent so follow-ups don't jump intents
            self._intent_lock = self._intent_lock or template_key
        
        # CRITICAL: High-risk query handling (BUT NOT DURING STEP-BY-STEP COLLECTION!)
        if classification.get("is_high_risk", False) and not self._step_by_step_collector:
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
        
        # If we asked a specific question in the last turn, use context-aware extraction
        if self._awaiting_slot:
            answer_text = (query or "").strip()
            slot = self._awaiting_slot

            # Initialize slots dict and merged_slots early for rejection handler
            slots = {}
            merged_slots = dict(self.session_slots)

            # PRIORITY: If step-by-step collector is active, route all responses to it
            if self._step_by_step_collector is not None:
                logger.info(f"Routing response to step-by-step collector: {answer_text[:50]}")
                response = self._step_by_step_collector.process_answer(answer_text)

                # Check if collection is complete
                if response.get("step_by_step_complete"):
                    logger.info("✅ Step-by-step collection complete - triggering therapy generation")
                    # Merge collected data into session_slots
                    collected_data = response.get("collected_data", {})
                    for k, v in collected_data.items():
                        if v is not None:  # Don't overwrite with None
                            self.session_slots[k] = v

                    # Clear collector and awaiting state
                    self._step_by_step_collector = None
                    self._awaiting_slot = None
                    self._intent_lock = None

                    # Log collected data for debugging
                    logger.info(f"Collected data: {list(collected_data.keys())}")

                    # Recursively call handle_query with a synthetic therapy request
                    # This will trigger normal therapy generation with all collected slots
                    synthetic_query = f"Generate personalized therapy plan for {collected_data.get('diagnosis', 'patient')}"
                    logger.info(f"Calling handle_query recursively with: {synthetic_query}")
                    return self.handle_query(synthetic_query)
                else:
                    # Still collecting - update awaiting_slot and return next question
                    self._awaiting_slot = response.get("awaiting_slot")
                    logger.info(f"Collector waiting for: {self._awaiting_slot}")
                    return response

            # SPECIAL HANDLER: data_collection_method (from therapy onboarding)
            # IMPORTANT: Only handle this if collector is NOT already active!
            if slot == "data_collection_method" and not self._step_by_step_collector:
                answer_lower = answer_text.lower().strip()

                if "step" in answer_lower or "2" in answer_lower:
                    # User chose step-by-step data collection
                    logger.info("User chose step-by-step data collection - initializing collector")
                    self._intent_lock = "therapy"  # Lock to therapy intent

                    # Initialize step-by-step collector with diagnosis and any existing slots
                    diagnosis = merged_slots.get("diagnosis")
                    self._step_by_step_collector = StepByStepTherapyCollector(
                        diagnosis=diagnosis,
                        initial_slots=merged_slots
                    )

                    # Start the collector - get first question
                    collector_response = self._step_by_step_collector.start()

                    # CRITICAL: Set awaiting_slot from collector response
                    self._awaiting_slot = collector_response.get("awaiting_slot")
                    logger.info(f"Collector started - awaiting slot: {self._awaiting_slot}")

                    return collector_response

                elif "upload" in answer_lower or "1" in answer_lower:
                    # User chose to upload lab results
                    logger.info("User chose to upload lab results")
                    self._awaiting_slot = None
                    return {
                        "template": "followup",
                        "answer": "📋 Please upload your lab results using the **[Upload Lab Results]** button below.\n\nI'll extract biomarker values (creatinine, eGFR, HbA1c, etc.) automatically from the PDF or photo.",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "citations": [],
                        "model_note": "Awaiting lab upload",
                        "warnings": ["therapy_onboarding"],
                        "composer_placeholder": "Click upload button",
                        "highlight_upload_button": True
                    }

                elif "general" in answer_lower or "3" in answer_lower:
                    # User chose general info first
                    logger.info("User chose general info (downgrade to recommendation)")
                    self._awaiting_slot = None
                    self._intent_lock = "recommendation"  # Downgrade to recommendation
                    classification["label"] = "recommendation"
                    classification["downgrade_reason"] = "user_chose_general_info"
                    classification["original_label"] = "therapy"

                    # Fall through to normal recommendation handling
                    template_key = "recommendation"

                else:
                    # Unclear response - ask again
                    return {
                        "template": "followup",
                        "answer": "Please choose one of the options:\n\n1. **Upload Lab Results** (fastest)\n2. **Step-by-Step** (I'll ask questions)\n3. **General Info First** (guidelines only)\n\nType '1', '2', or '3':",
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "citations": [],
                        "model_note": "Clarifying data collection method",
                        "warnings": ["therapy_onboarding"],
                        "composer_placeholder": "Choose 1, 2, or 3"
                    }

            # CRITICAL: Use new context-aware extraction from classifier
            extracted = self.classifier.extract_from_followup_response(answer_text, slot)

            # Handle rejection first
            if not extracted.get("found") and extracted.get("reason") == "user_rejected":
                # User rejected - offer graceful degradation
                return self._handle_slot_rejection(slot, "user_rejected", classification, merged_slots)

            # Handle biomarker slots with values
            if extracted.get("found") and slot in BIOMARKERS:
                # Successfully extracted biomarker value
                biomarker_data = {
                    "value": extracted["value"],
                    "unit": extracted["unit"],
                    "biomarker": extracted["biomarker"]
                }
                slots[slot] = biomarker_data
                self.session_slots[slot] = biomarker_data
                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0
                logger.info(f"✅ Extracted {slot}: {extracted['value']} {extracted['unit']}")
                # Fall through to continue

            # Handle medication slots
            elif extracted.get("found") and slot == "medications":
                medications = extracted["medications"]
                slots[slot] = medications
                self.session_slots[slot] = medications
                self._awaiting_slot = None
                self._awaiting_question = None
                self._retry_count = 0
                logger.info(f"✅ Extracted medications: {medications}")
                # Fall through

            # Handle unclear response or out of range
            elif not extracted.get("found"):
                if extracted.get("reason") == "out_of_range":
                    # Value seems unusual - ask for confirmation
                    return {
                        "template": "followup",
                        "answer": extracted.get("message", f"That value seems unusual. Please confirm or re-enter."),
                        "followups": [],
                        "model_used": "none",
                        "therapy_output": None,
                        "therapy_summary": None,
                        "sources_used": [],
                        "model_note": "Value out of range",
                        "warnings": ["value_validation"],
                        "composer_placeholder": "Confirm or re-enter value"
                    }
                else:
                    # Unclear response - retry or use old parser
                    pass  # Fall through to existing parser

            # Special handling: If awaiting confirmation for medications (legacy path)
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

        # Merge slots with session (slots already extracted earlier if not awaiting)
        merged_slots = dict(self.session_slots)
        for k, v in slots.items():
            if v is not None:
                merged_slots[k] = v

        # PHASE 4 CLEANUP: Old slot validation loop removed
        # Step-by-step collector handles all data collection for therapy intents
        # No need for dual validation system
        
        # PHASE 4 CLEANUP: Medication check only for non-step-by-step flows
        # Step-by-step collector handles all data collection including medications
        if template_key in ["therapy", "dermatology"] and not self._step_by_step_collector:
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
            "composer_placeholder": self._awaiting_question or "",
            "classification": classification  # Include classification for testing/debugging
        }