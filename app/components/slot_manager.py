# app/components/slot_manager.py
import threading
import datetime
from typing import Dict, Any, Optional, List
from app.components.followup_question_generator import FollowUpQuestionGenerator

class SlotManager:
    """
    Manages session-based pediatric patient data:
    - Updates and validates slots (age, height, weight, diagnosis, etc.)
    - Computes BMI and classifies weight status
    - Tracks rejections and missing information
    - Provides pediatric-friendly prompts via FollowUpQuestionGenerator
    """

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.followup = FollowUpQuestionGenerator()

    # -------------------------
    # Session Management
    # -------------------------
    def create_session(self, session_id: str, clinician_id: Optional[str] = None):
        with self.lock:
            self.sessions[session_id] = {
                "clinician_id": clinician_id,
                "created_at": datetime.datetime.utcnow().isoformat(),
                "slots": {},
                "awaiting_slot": None,
                "retry_counts": {},
                "rejections": {},
            }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        with self.lock:
            return self.sessions.get(session_id, {})

    def clear_session(self, session_id: str):
        with self.lock:
            if session_id in self.sessions:
                self.sessions[session_id]["slots"] = {}

    # -------------------------
    # Slot Operations
    # -------------------------
    def update_slot(self, session_id: str, slot: str, value: Any, source: str = "user") -> Dict[str, Any]:
        with self.lock:
            session = self.sessions.setdefault(session_id, {"slots": {}})
            slots = session["slots"]

            # Normalize
            normalized_value = self._normalize_value(slot, value)
            slots[slot] = normalized_value

            # Derived calculation (BMI)
            if slot in ["height_cm", "weight_kg", "age"]:
                self._compute_bmi(session_id)

            session["updated_at"] = datetime.datetime.utcnow().isoformat()
            return slots

    def batch_update(self, session_id: str, slot_dict: Dict[str, Any]):
        for slot, value in slot_dict.items():
            self.update_slot(session_id, slot, value, source="upload")

    def get_missing_slots(self, session_id: str, intent: str) -> List[str]:
        """Delegate logic to followup_question_generator"""
        profile = self.sessions.get(session_id, {}).get("slots", {})
        lab_results = profile.get("lab_results", [])
        return self.followup._get_missing_slots(intent, profile, lab_results)

    # -------------------------
    # BMI Computation
    # -------------------------
    def _compute_bmi(self, session_id: str):
        session = self.sessions.get(session_id)
        if not session:
            return

        slots = session.get("slots", {})
        height = slots.get("height_cm")
        weight = slots.get("weight_kg")
        age = slots.get("age")

        if not all([height, weight, age]):
            return

        try:
            height_m = float(height) / 100
            bmi = float(weight) / (height_m ** 2)
            slots["bmi"] = round(bmi, 2)

            # Pediatric warning placeholder (simple classification)
            if bmi < 13:
                slots["bmi_category"] = "Underweight"
            elif 13 <= bmi < 17:
                slots["bmi_category"] = "Healthy weight"
            elif 17 <= bmi < 19:
                slots["bmi_category"] = "Overweight (watch closely)"
            else:
                slots["bmi_category"] = "Obesity (requires attention)"

            return {"bmi": slots["bmi"], "category": slots["bmi_category"]}
        except Exception:
            return None

    # -------------------------
    # Helpers
    # -------------------------
    def _normalize_value(self, slot: str, value: Any) -> Any:
        """Normalize units or formats"""
        if slot == "age":
            if isinstance(value, str):
                value = value.lower().replace("years", "").replace("year", "").replace("y", "").strip()
            try:
                return int(float(value))
            except Exception:
                return None
        if slot in ["height_cm", "weight_kg"]:
            try:
                return round(float(value), 2)
            except Exception:
                return None
        return value

    # -------------------------
    # Rejections and Prompts
    # -------------------------
    def mark_rejection(self, session_id: str, slot: str, reason: str):
        session = self.sessions.get(session_id)
        if not session:
            return
        r = session["rejections"].get(slot, 0)
        session["rejections"][slot] = r + 1
        session["retry_counts"][slot] = session["rejections"][slot]

        # Apply default if max retries reached
        if session["rejections"][slot] >= 2:
            if slot == "country":
                session["slots"]["country"] = "Nigeria"
            elif slot == "age":
                session["slots"]["age"] = 5
            elif slot == "biomarkers":
                session["slots"]["biomarkers"] = {}
            return {"action": "auto_default", "slot": slot}

        return {"action": "retry", "slot": slot, "reason": reason}

    def get_prompt_for_slot(self, slot: str) -> str:
        """Use followup_question_generator to get pediatric phrasing"""
        return self.followup._create_question_for_slot(slot)

    # -------------------------
    # Profile Export
    # -------------------------
    def export_profile_summary(self, session_id: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id, {})
        slots = session.get("slots", {})
        return {
            "age": slots.get("age"),
            "sex": slots.get("sex"),
            "diagnosis": slots.get("diagnosis"),
            "bmi": slots.get("bmi"),
            "bmi_category": slots.get("bmi_category"),
            "country": slots.get("country"),
            "medications": slots.get("medications"),
            "biomarkers": list(slots.get("biomarkers", {}).keys()) if slots.get("biomarkers") else [],
        }