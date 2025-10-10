import logging
from app.common.logger import get_logger
logger = get_logger(__name__)
from typing import List

class FollowUpQuestionGenerator:
    def __init__(self):
        # Define slot priority order (critical first)
        self.slot_priority = [
            "diagnosis",  # Critical for therapy mode
            "age", "sex",  # Basic demographics
            "weight_kg", "height_cm",  # Needed for BMI calculation
            "medications",  # Needed for drug-nutrient interactions (optional)
            "allergies",  # Critical for safety (optional)
            "key_biomarkers",  # Optional - many patients don't have recent labs
            "country",  # Optional - defaults available
            "dietary_patterns",  # Lower priority
        ]
    
    def generate_follow_up_question(self, query_info: dict, profile: dict, lab_results: list, clarifications: dict) -> dict:
        """
        Generate ONE follow-up question per turn, prioritizing critical slots.
        Returns a dictionary with:
        - question: the question to ask
        - slot: the slot name this question relates to
        - composer_placeholder: the exact text to show in the composer placeholder
        """
        # Determine what's missing based on intent
        intent = query_info.get("label", "general")
        missing_slots = self._get_missing_slots(intent, profile, lab_results)
        invalid_slots = self._get_invalid_slots(query_info, profile, lab_results)
        
        # Prioritize invalid reasons over missing slots
        if invalid_slots:
            # Return first invalid reason as clarification question
            invalid_question = self._create_invalid_question(invalid_slots[0])
            return {
                "question": invalid_question,
                "slot": invalid_slots[0],
                "composer_placeholder": invalid_question
            }
        
        # If no invalid slots, check for missing slots
        if not missing_slots:
            return None
        
        # Find highest priority missing slot
        for slot in self.slot_priority:
            if slot in missing_slots:
                question = self._create_question_for_slot(slot, intent)
                return {
                    "question": question,
                    "slot": slot,
                    "composer_placeholder": question
                }
        
        # Fallback to first missing slot
        question = self._create_question_for_slot(missing_slots[0], intent)
        return {
            "question": question,
            "slot": missing_slots[0],
            "composer_placeholder": question
        }
    
    def _get_missing_slots(self, intent: str, profile: dict, lab_results: list) -> List[str]:
        """Determine which slots are missing for this intent"""
        missing = []
        
        # Common slots across intents
        if not profile or not profile.get("weight_kg") and not profile.get("weight"):
            missing.append("weight_kg")
        if not profile or not profile.get("height_cm") and not profile.get("height"):
            missing.append("height_cm")
        if not profile or not profile.get("diagnosis"):
            missing.append("diagnosis")
        if not profile or not profile.get("medications"):
            missing.append("medications")
        if not profile or not profile.get("allergies") or profile.get("allergies") is None:
            missing.append("allergies")
        if not profile or not profile.get("country"):
            missing.append("country")
        
        # Intent-specific slots
        # Note: key_biomarkers is now optional for therapy - removed from required checks
        elif intent == "comparison":
            if not profile or not profile.get("food_a") or not profile.get("food_b"):
                missing.append("food_a")
                missing.append("food_b")
        
        return missing
    
    def _get_invalid_slots(self, query_info: dict, profile: dict, lab_results: list) -> List[str]:
        """Determine which slots have invalid values for this intent"""
        invalid = []
        
        # Check for invalid values in profile
        if profile:
            # Check age
            if "age" in profile:
                try:
                    age_val = int(profile["age"])
                    if age_val < 0 or age_val > 120:
                        invalid.append("age")
                except Exception:
                    invalid.append("age")
            
            # Check height
            if "height_cm" in profile:
                try:
                    height_val = float(profile["height_cm"])
                    if height_val < 50 or height_val > 250:
                        invalid.append("height_cm")
                except Exception:
                    invalid.append("height_cm")
            
            # Check weight
            if "weight_kg" in profile:
                try:
                    weight_val = float(profile["weight_kg"])
                    if weight_val < 10 or weight_val > 400:
                        invalid.append("weight_kg")
                except Exception:
                    invalid.append("weight_kg")
        
        return invalid
    
    def _create_invalid_question(self, slot: str) -> str:
        """Create a clarification question for an invalid slot value"""
        if slot == "age":
            return "What is your age in years? (Must be between 0 and 120)"
        elif slot == "height_cm":
            return "What is your height in centimeters? (Must be between 50 and 250 cm)"
        elif slot == "weight_kg":
            return "What is your weight in kilograms? (Must be between 10 and 400 kg)"
        elif slot == "country":
            return "Which country's Food Composition Table should I use? (e.g., Nigeria, Kenya, Canada)"
        elif slot == "medications":
            return "Are you currently taking any medications? If yes, please list them."
        elif slot == "allergies":
            return "Do you have any food allergies (e.g., peanuts, dairy, gluten, soy)? Please list them or say 'none'."
        elif slot == "key_biomarkers":
            return "Please provide your most recent lab results (e.g., HbA1c, creatinine, eGFR)."
        return f"Clarify: {slot} value is invalid"
    
    def _create_question_for_slot(self, slot: str, intent: str) -> str:
        """Create a single, clear question for a specific slot"""
        if slot == "weight_kg":
            return "What is your current weight in kilograms?"
        elif slot == "height_cm":
            return "What is your current height in centimeters?"
        elif slot == "diagnosis":
            return "What is your diagnosis or medical condition?"
        elif slot == "medications":
            return "Are you currently taking any medications? If yes, please list them."
        elif slot == "allergies":
            return "Do you have any food allergies (e.g., peanuts, dairy, gluten, soy)? Please list them or say 'none'."
        elif slot == "country":
            return "Which country's Food Composition Table should I use? (e.g., Nigeria, Kenya, Canada)"
        elif slot == "key_biomarkers":
            return "Please provide your most recent lab results (e.g., HbA1c, creatinine, eGFR)."
        elif slot == "food_a" or slot == "food_b":
            return "Please name the foods you want to compare."
        return f"Please provide {slot.replace('_', ' ')} information."