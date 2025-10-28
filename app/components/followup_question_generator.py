# app/components/followup_question_generator.py
import logging
from app.common.logger import get_logger
logger = get_logger(__name__)
from typing import List, Optional, Dict, Any

class FollowUpQuestionGenerator:
    def __init__(self):
        # Slot priority order tuned to your requirements (critical first)
        self.slot_priority = [
            "diagnosis",      # Critical for therapy mode
            "age",            # demographics
            "medications",    # must-have for therapy
            "country",        # for FCT mapping
            "biomarkers",     # must-have for therapy (can be multiple)
            "height_cm",      # requested when necessary (e.g., for BMI/energy)
            "weight_kg",
            "allergies",
            "dietary_patterns",
        ]

        # Step-by-step slots order for therapy "step by step" flow
        self.step_by_step_slots = ["age", "medications", "country", "biomarkers"]

    def generate_follow_up_question(self, query_info: dict, profile: dict, lab_results: list, clarifications: dict) -> Optional[dict]:
        """
        Generate ONE follow-up question per turn, prioritizing critical slots.
        If query_info indicates a gatekeeper downgrade, return the educational fallback prompt.

        CRITICAL FIX: For therapy intent, if critical requirements (meds/biomarkers) are rejected,
        return None to trigger gatekeeper enforcement immediately.
        """
        # If gatekeeper downgraded from therapy -> recommendation, present single educational fallback prompt
        if query_info.get("downgrade_reason"):
            # The classifier already provided fallback_options and educational_text
            edu_text = query_info.get("educational_text") or ""
            fallback_options = query_info.get("fallback_options") or []
            # Build prompt text preferring concise UX
            options_text = " / ".join([f"{opt['id']}: {opt['text']}" for opt in fallback_options])
            prompt = edu_text + "\n\nOptions: " + options_text
            return {
                "question": prompt,
                "slot": "fallback_choice",
                "composer_placeholder": "Reply 'upload', 'step by step', or 'overview'"
            }

        # Otherwise follow normal missing-slot flow
        intent = query_info.get("label", "general")

        # CRITICAL FIX (APPROACH 3): For therapy intent, check if critical requirements are rejected
        # If medications OR biomarkers are rejected, don't ask for optional slots - let gatekeeper handle
        if intent == "therapy":
            meds_rejected = self._is_slot_rejected(profile, "medications")
            biomarkers_rejected = self._is_slot_rejected(profile, "biomarkers")

            # If EITHER critical requirement is rejected, stop asking questions
            # This allows the gatekeeper in _handle_therapy to catch it and downgrade
            if meds_rejected or biomarkers_rejected:
                # Return None = no more questions = proceed to gatekeeper check
                return None

        missing_slots = self._get_missing_slots(intent, profile, lab_results)
        invalid_slots = self._get_invalid_slots(profile)

        # Prioritize invalid slots
        if invalid_slots:
            slot = invalid_slots[0]
            return {
                "question": self._create_invalid_question(slot),
                "slot": slot,
                "composer_placeholder": self._create_invalid_question(slot)
            }

        # If nothing missing - no follow-up needed
        if not missing_slots:
            return None

        # If the user explicitly indicated "step by step" in clarifications, follow that order
        if clarifications and clarifications.get("mode") == "step_by_step":
            for slot in self.step_by_step_slots:
                if slot in missing_slots:
                    q = self._create_question_for_slot(slot)
                    return {"question": q, "slot": slot, "composer_placeholder": q}

        # Default: choose by slot_priority
        # CRITICAL FIX: For therapy intent, prioritize biomarkers BEFORE country
        priority_list = self.slot_priority.copy()
        if intent == "therapy":
            # Reorder: biomarkers must come before country for therapy
            if "biomarkers" in priority_list and "country" in priority_list:
                priority_list.remove("biomarkers")
                country_idx = priority_list.index("country")
                # Insert biomarkers right before country
                priority_list.insert(country_idx, "biomarkers")

        for slot in priority_list:
            if slot in missing_slots:
                q = self._create_question_for_slot(slot)
                return {"question": q, "slot": slot, "composer_placeholder": q}

        # Fallback to first missing slot
        slot = missing_slots[0]
        q = self._create_question_for_slot(slot)
        return {"question": q, "slot": slot, "composer_placeholder": q}

    def generate_fallback_choice_prompt(self, fallback_options: List[Dict[str, str]]) -> dict:
        """
        Generate a single user prompt showing the three fallback choices.
        This can be used independently by the orchestrator if desired.
        """
        options_text = "\n".join([f"{opt['id']}: {opt['text']}" for opt in fallback_options])
        prompt = (
            "I can only provide an overview because a full therapy plan needs both medication and biomarker data.\n\n"
            "Please choose one of the options below:\n" + options_text +
            "\n\nReply with 'upload', 'step by step', or 'overview'."
        )
        return {"question": prompt, "slot": "fallback_choice", "composer_placeholder": "upload / step by step / overview"}

    def _is_slot_rejected(self, profile: dict, slot_name: str) -> bool:
        """Check if a slot was explicitly rejected by user"""
        return (
            profile.get(f"_rejected_{slot_name}") or
            profile.get(slot_name) == "user_declined"
        )

    def _is_slot_actually_filled(self, profile: dict, slot_name: str) -> bool:
        """Helper: Check if a slot is actually filled with valid data"""
        value = profile.get(slot_name)

        # Check if None or empty string
        if value is None or value == "":
            return False

        # Check if empty list
        if isinstance(value, list) and len(value) == 0:
            return False

        # Check if marked as declined (not valid data)
        if value == "user_declined":
            return False

        # Otherwise it's filled with actual data
        return True

    def _get_missing_slots(self, intent: str, profile: dict, lab_results: list) -> List[str]:
        """Determine which slots are missing for this intent"""
        missing = []

        # Profile may be None
        profile = profile or {}

        # CRITICAL FIX: Only add to missing if NOT rejected AND NOT filled
        # Weight/height best-effort detection: accept 'weight' or 'weight_kg'; 'height' or 'height_cm'
        if not self._is_slot_rejected(profile, "weight_kg") and not self._is_slot_actually_filled(profile, "weight_kg") and not self._is_slot_actually_filled(profile, "weight"):
            missing.append("weight_kg")
        if not self._is_slot_rejected(profile, "height_cm") and not self._is_slot_actually_filled(profile, "height_cm") and not self._is_slot_actually_filled(profile, "height"):
            missing.append("height_cm")
        if not self._is_slot_rejected(profile, "diagnosis") and not self._is_slot_actually_filled(profile, "diagnosis"):
            missing.append("diagnosis")
        if not self._is_slot_rejected(profile, "age") and not self._is_slot_actually_filled(profile, "age"):
            missing.append("age")

        # For therapy/recommendation, medications and allergies are important
        if intent in ["therapy", "recommendation"]:
            if not self._is_slot_rejected(profile, "medications") and not self._is_slot_actually_filled(profile, "medications"):
                missing.append("medications")
            # Allergies still important for safety
            if not self._is_slot_rejected(profile, "allergies") and not self._is_slot_actually_filled(profile, "allergies"):
                missing.append("allergies")

        # Country mapping for FCT usage
        if not profile.get("country"):
            missing.append("country")

        # Biomarkers: optional for recommendation, required for therapy (but gatekeeper already enforced)
        if intent == "therapy":
            # in therapy mode we assume gatekeeper validated having both meds and biomarkers
            if not profile.get("biomarkers") and not lab_results:
                missing.append("biomarkers")

        # Comparison intent: need two foods
        if intent == "comparison":
            if not profile.get("food_a") or not profile.get("food_b"):
                missing.extend(["food_a", "food_b"])

        # Remove duplicates while preserving order
        seen = set()
        final_missing = []
        for s in missing:
            if s not in seen:
                seen.add(s)
                final_missing.append(s)

        return final_missing

    def _get_invalid_slots(self, profile: dict) -> List[str]:
        """Return list of invalid slots (e.g., bad age)"""
        invalid = []
        if not profile:
            return invalid

        if "age" in profile:
            try:
                age_val = int(profile["age"])
                if age_val < 0 or age_val > 120:
                    invalid.append("age")
            except Exception:
                invalid.append("age")

        if "height_cm" in profile:
            try:
                height_val = float(profile["height_cm"])
                if height_val < 30 or height_val > 250:
                    invalid.append("height_cm")
            except Exception:
                invalid.append("height_cm")

        if "weight_kg" in profile:
            try:
                weight_val = float(profile["weight_kg"])
                if weight_val < 2 or weight_val > 400:
                    invalid.append("weight_kg")
            except Exception:
                invalid.append("weight_kg")

        return invalid

    def _create_invalid_question(self, slot: str) -> str:
        if slot == "age":
            return "What is the patient's age in years? (0-120)"
        elif slot == "height_cm":
            return "What is the patient's height in centimeters? (e.g., 85)"
        elif slot == "weight_kg":
            return "What is the patient's weight in kilograms? (e.g., 12.5)"
        elif slot == "country":
            return "Which country's Food Composition Table should I use? (e.g., Nigeria, Kenya, Canada)"
        elif slot == "medications":
            return "Please list current medications (include dose/frequency if possible), or say 'none'."
        elif slot == "allergies":
            return "Please list any known food allergies (or say 'none')."
        elif slot == "biomarkers":
            return "Please provide recent lab results (e.g., creatinine 0.6 mg/dL, HbA1c 7.2%). You can upload a lab PDF or type values."
        return f"Clarify {slot}."

    def _create_question_for_slot(self, slot: str) -> str:
        """Return a single clear question for the requested slot"""
        if slot == "weight_kg":
            return "What is the patient's current weight in kilograms?"
        elif slot == "height_cm":
            return "What is the patient's current height in centimeters?"
        elif slot == "diagnosis":
            return "What is the diagnosis or medical condition?"
        elif slot == "medications":
            return "Are any medications being taken? If yes, please list them (or say 'none')."
        elif slot == "allergies":
            return "Any food allergies? List them or say 'none'."
        elif slot == "country":
            return "Which country's Food Composition Table should I use? (e.g., Nigeria, Kenya)"
        elif slot == "biomarkers":
            return "Please provide recent lab values (e.g., creatinine 0.6 mg/dL; HbA1c 7.2%). You can upload a file."
        elif slot == "food_a" or slot == "food_b":
            return "Please name the food to compare."
        elif slot == "age":
            return "What is the patient's age in years?"
        return f"Please provide {slot.replace('_',' ')}."

    # ============================================================================
    # NEW METHODS FOR THERAPY FLOW
    # ============================================================================

    def validate_diagnosis_for_therapy(self, diagnosis: Optional[str]) -> Dict[str, Any]:
        """
        Validate if diagnosis is supported for therapy flow.

        Uses SUPPORTED_THERAPY_CONDITIONS from query_classifier.

        Args:
            diagnosis: Diagnosis to validate

        Returns:
            Dict with keys:
            - valid: bool (True if in supported therapy list)
            - diagnosis_normalized: str (canonical name if valid)
            - message: str (explanation if not valid)
        """
        if not diagnosis:
            return {
                "valid": False,
                "diagnosis_normalized": None,
                "message": "No diagnosis provided"
            }

        # Import here to avoid circular dependency
        from app.components.query_classifier import SUPPORTED_THERAPY_CONDITIONS

        diagnosis_lower = diagnosis.lower().strip()

        # Check if in supported list
        if diagnosis_lower in SUPPORTED_THERAPY_CONDITIONS:
            return {
                "valid": True,
                "diagnosis_normalized": SUPPORTED_THERAPY_CONDITIONS[diagnosis_lower],
                "message": f"Diagnosis '{diagnosis}' is supported for therapy planning"
            }

        # Partial match
        for key, canonical in SUPPORTED_THERAPY_CONDITIONS.items():
            if key in diagnosis_lower or diagnosis_lower in key:
                return {
                    "valid": True,
                    "diagnosis_normalized": canonical,
                    "message": f"Diagnosis '{diagnosis}' mapped to '{canonical}' for therapy planning"
                }

        # Not in supported list
        return {
            "valid": False,
            "diagnosis_normalized": None,
            "message": f"Diagnosis '{diagnosis}' is not in the supported therapy list. Supported conditions: {', '.join(set(SUPPORTED_THERAPY_CONDITIONS.values()))}"
        }

    def generate_3_option_nudge(
        self,
        missing_critical_data: List[str]
    ) -> Dict[str, Any]:
        """
        Generate 3-option nudge when therapy requires data but it's missing.

        Options:
        A. Upload medical records (extract meds + biomarkers)
        B. Step-by-step Q&A (guided slot filling)
        C. General info only (downgrade to recommendation)

        Args:
            missing_critical_data: List of missing slots (e.g., ["medications", "biomarkers"])

        Returns:
            Dict with question, options list, slot name
        """
        missing_str = " and ".join(missing_critical_data)

        question = (
            f"To create a personalized therapeutic meal plan, I need {missing_str}. "
            f"How would you like to proceed?\n\n"
            f"🅰️ **Upload medical records** - I'll extract the information automatically\n"
            f"🅱️ **Step-by-step questions** - I'll ask for each piece of information\n"
            f"🅲️ **General dietary info only** - Skip personalized therapy planning\n\n"
            f"Please reply with A, B, or C."
        )

        options = [
            {
                "id": "upload",
                "label": "🅰️ Upload medical records",
                "text": "Upload",
                "action": "upload_file"
            },
            {
                "id": "step_by_step",
                "label": "🅱️ Step-by-step questions",
                "text": "Step by step",
                "action": "guided_qa"
            },
            {
                "id": "general_info",
                "label": "🅲️ General dietary info only",
                "text": "General info",
                "action": "downgrade_to_recommendation"
            }
        ]

        return {
            "question": question,
            "slot": "nudge_choice",
            "options": options,
            "missing_data": missing_critical_data,
            "composer_placeholder": "Reply 'A', 'B', or 'C'"
        }

    def should_trigger_nudge(
        self,
        intent: str,
        profile: Dict[str, Any]
    ) -> bool:
        """
        Determine if 3-option nudge should be triggered.

        Trigger when:
        - Intent is therapy
        - Missing medications OR biomarkers

        Args:
            intent: Query intent
            profile: User profile with slots

        Returns:
            True if nudge should be triggered
        """
        if intent != "therapy":
            return False

        # Check if critical slots are missing
        has_meds = self._is_slot_actually_filled(profile, "medications")
        has_biomarkers = self._is_slot_actually_filled(profile, "biomarkers")

        # Trigger nudge if either is missing
        return not (has_meds and has_biomarkers)
