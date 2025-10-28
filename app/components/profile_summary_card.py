# app/components/profile_summary_card.py
"""
ProfileSummaryCard

Generates and formats Profile Summary Cards for therapy queries only.
Cards are progressively populated through the 7-step therapy flow.

Usage:
    card = ProfileSummaryCard.initialize_card(patient_info)
    card.update_step(1, dri_baseline_data)
    card.update_step(2, therapeutic_adjustments)
    display_text = card.format_for_display()
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProfileSummaryCard:
    """
    Profile Summary Card for therapy queries.

    Progressively populated through 7-step therapy flow:
    - Step 1: Baseline DRI requirements
    - Step 2: Therapeutic adjustments
    - Step 3: Biochemical rationale
    - Step 4: Drug-nutrient interactions
    - Step 5: Food sources
    - Step 7: Meal plan (if generated)
    """

    # Patient information
    patient_info: Dict[str, Any] = field(default_factory=dict)

    # Therapy flow data (populated progressively)
    baseline_requirements: Optional[Dict[str, Any]] = None
    therapeutic_adjustments: Optional[Dict[str, Any]] = None
    biochemical_context: Optional[str] = None
    drug_nutrient_notes: Optional[List[str]] = None
    food_sources: Optional[Dict[str, List[Dict]]] = None
    meal_plan_summary: Optional[Dict[str, Any]] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    completed_steps: List[int] = field(default_factory=list)

    @classmethod
    def initialize_card(cls, patient_info: Dict[str, Any]) -> "ProfileSummaryCard":
        """
        Initialize a new Profile Summary Card.

        Args:
            patient_info: Dict with keys:
                - age (int): Patient age in years
                - sex (str): "M" or "F"
                - weight_kg (float): Weight in kg
                - height_cm (float): Height in cm
                - diagnosis (str): Normalized diagnosis
                - medications (list): List of medications
                - biomarkers (dict): Biomarker values
                - country (str): Country for FCT mapping

        Returns:
            Initialized ProfileSummaryCard
        """
        logger.info(f"Initializing Profile Summary Card for diagnosis: {patient_info.get('diagnosis')}")
        return cls(patient_info=patient_info)

    def update_step(self, step: int, data: Any) -> None:
        """
        Update card with data from a specific therapy step.

        Args:
            step: Step number (1-7)
            data: Step-specific data
        """
        if step == 1:
            self.baseline_requirements = data
        elif step == 2:
            self.therapeutic_adjustments = data
        elif step == 3:
            self.biochemical_context = data
        elif step == 4:
            self.drug_nutrient_notes = data
        elif step == 5:
            self.food_sources = data
        elif step == 7:
            self.meal_plan_summary = data
        else:
            logger.warning(f"Invalid step number: {step}")
            return

        if step not in self.completed_steps:
            self.completed_steps.append(step)

        self.last_updated = datetime.now()
        logger.debug(f"Profile card updated: Step {step} completed")

    def is_complete(self) -> bool:
        """Check if all required steps are completed (Steps 1-5 minimum)"""
        required_steps = [1, 2, 3, 4, 5]
        return all(step in self.completed_steps for step in required_steps)

    def format_for_display(self) -> str:
        """
        Format card for display with progressive content.

        Returns:
            Formatted markdown string with emoji headers
        """
        lines = []

        # Header
        lines.append("┌" + "─" * 58 + "┐")
        lines.append("│ 📋 PROFILE SUMMARY CARD" + " " * 34 + "│")
        lines.append("├" + "─" * 58 + "┤")

        # Patient Information
        info = self.patient_info
        lines.append(f"│ Patient: {info.get('age')} years, {info.get('sex')}, "
                     f"{info.get('weight_kg')}kg, {info.get('height_cm')}cm")
        lines.append(f"│ Diagnosis: {info.get('diagnosis', 'Not specified')}")

        # Medications
        meds = info.get('medications', [])
        if meds:
            meds_str = ", ".join(meds[:3])  # Show first 3
            if len(meds) > 3:
                meds_str += f" (+{len(meds) - 3} more)"
            lines.append(f"│ Medications: {meds_str}")

        # Key Biomarkers
        biomarkers = info.get('biomarkers', {})
        if biomarkers:
            # Show up to 3 key biomarkers
            bio_items = []
            for key, value in list(biomarkers.items())[:3]:
                if isinstance(value, dict):
                    bio_items.append(f"{key.upper()}: {value.get('value')} {value.get('unit', '')}")
                else:
                    bio_items.append(f"{key.upper()}: {value}")

            if bio_items:
                lines.append(f"│ Biomarkers: {', '.join(bio_items)}")

        # Country and FCT
        country = info.get('country')
        if country:
            lines.append(f"│ Country: {country}")

        lines.append("│" + " " * 58 + "│")

        # STEP 1: Baseline Requirements
        if self.baseline_requirements:
            lines.append("│ 🎯 BASELINE NUTRIENT TARGETS (DRI):" + " " * 21 + "│")
            baseline = self.baseline_requirements

            # Show macros first
            for nutrient in ["energy", "protein", "carbohydrate", "fat", "fiber"]:
                if nutrient in baseline:
                    value = baseline[nutrient]
                    if isinstance(value, dict):
                        val_str = f"{value.get('value')} {value.get('unit', '')}"
                    else:
                        val_str = str(value)
                    lines.append(f"│   • {nutrient.capitalize()}: {val_str}")

            lines.append("│   • [... 15 more micronutrients ...]")
            lines.append("│" + " " * 58 + "│")

        # STEP 2: Therapeutic Adjustments
        if self.therapeutic_adjustments:
            lines.append("│ 🔧 THERAPEUTIC ADJUSTMENTS:" + " " * 30 + "│")
            adjustments = self.therapeutic_adjustments

            # Show sample adjustments (up to 3)
            count = 0
            for nutrient, adj_data in adjustments.items():
                if count >= 3:
                    remaining = len(adjustments) - 3
                    lines.append(f"│   • [... {remaining} more adjustments ...]")
                    break

                if isinstance(adj_data, dict):
                    baseline_val = adj_data.get('baseline', '?')
                    adjusted_val = adj_data.get('adjusted', '?')
                    reason = adj_data.get('reason', '')

                    if baseline_val != adjusted_val:
                        lines.append(f"│   • {nutrient.capitalize()}: {baseline_val} → {adjusted_val}")
                        if reason:
                            lines.append(f"│     Reason: {reason[:45]}...")
                        count += 1

            lines.append("│" + " " * 58 + "│")

        # STEP 3: Biochemical Context
        if self.biochemical_context:
            lines.append("│ 🧬 BIOCHEMICAL RATIONALE:" + " " * 32 + "│")
            context = self.biochemical_context[:150]  # Truncate if too long
            lines.append(f"│   {context}...")
            lines.append("│" + " " * 58 + "│")

        # STEP 4: Drug-Nutrient Notes
        if self.drug_nutrient_notes:
            lines.append("│ 💊 DRUG-NUTRIENT INTERACTIONS:" + " " * 26 + "│")
            for note in self.drug_nutrient_notes[:3]:  # Show first 3
                lines.append(f"│   • {note[:54]}")
            if len(self.drug_nutrient_notes) > 3:
                lines.append(f"│   • [... {len(self.drug_nutrient_notes) - 3} more interactions ...]")
            lines.append("│" + " " * 58 + "│")

        # STEP 5: Food Sources (Summary)
        if self.food_sources:
            lines.append("│ 🥗 TOP FOOD SOURCES (Country-specific):" + " " * 18 + "│")

            # Show sample food sources for 3 nutrients
            count = 0
            for nutrient, foods in self.food_sources.items():
                if count >= 3:
                    break

                if foods:
                    food_names = [f.get('food', f) if isinstance(f, dict) else f for f in foods[:3]]
                    foods_str = ", ".join(food_names)
                    lines.append(f"│   {nutrient.capitalize()}: {foods_str[:48]}")
                    count += 1

            lines.append("│   [... rest of nutrients ...]")
            lines.append("│" + " " * 58 + "│")

        # STEP 7: Meal Plan Summary
        if self.meal_plan_summary:
            lines.append("│ 📅 3-DAY MEAL PLAN: Generated ✓" + " " * 25 + "│")
            summary = self.meal_plan_summary
            if 'total_meals' in summary:
                lines.append(f"│   Total meals: {summary['total_meals']}")
            if 'nutrient_compliance' in summary:
                compliance = summary['nutrient_compliance']
                lines.append(f"│   Nutrient targets met: {compliance}%")
            lines.append("│" + " " * 58 + "│")

        # Status
        status = "✅ Complete" if self.is_complete() else "⏳ In Progress"
        steps_completed = f"{len(self.completed_steps)}/7 steps"
        lines.append(f"│ Status: {status} ({steps_completed})" + " " * (58 - len(f"Status: {status} ({steps_completed})") - 2) + "│")

        # Footer
        lines.append("└" + "─" * 58 + "┘")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert card to dictionary for JSON serialization.

        Returns:
            Dict representation of card
        """
        return {
            "patient_info": self.patient_info,
            "baseline_requirements": self.baseline_requirements,
            "therapeutic_adjustments": self.therapeutic_adjustments,
            "biochemical_context": self.biochemical_context,
            "drug_nutrient_notes": self.drug_nutrient_notes,
            "food_sources": self.food_sources,
            "meal_plan_summary": self.meal_plan_summary,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "completed_steps": self.completed_steps,
            "is_complete": self.is_complete()
        }

    @staticmethod
    def should_display_card(intent: str) -> bool:
        """
        Determine if Profile Summary Card should be displayed.

        Args:
            intent: Query intent type

        Returns:
            True if intent is "therapy", False otherwise
        """
        return intent.lower() == "therapy"


# Example usage and testing
if __name__ == "__main__":
    # Test Profile Summary Card
    patient_info = {
        "age": 8,
        "sex": "M",
        "weight_kg": 25,
        "height_cm": 125,
        "diagnosis": "Type 1 Diabetes",
        "medications": ["Insulin (20 units/day)", "Metformin (500mg)"],
        "biomarkers": {
            "hba1c": {"value": 8.5, "unit": "%"},
            "glucose": {"value": 180, "unit": "mg/dL"}
        },
        "country": "Kenya"
    }

    card = ProfileSummaryCard.initialize_card(patient_info)

    # Simulate progressive updates
    card.update_step(1, {
        "energy": {"value": 1650, "unit": "kcal"},
        "protein": {"value": 45, "unit": "g"},
        "carbohydrate": {"value": 220, "unit": "g"},
        "fat": {"value": 55, "unit": "g"},
        "fiber": {"value": 20, "unit": "g"}
    })

    card.update_step(2, {
        "energy": {"baseline": 1500, "adjusted": 1650, "reason": "10% increase for T1D management"},
        "carbohydrate": {"baseline": 200, "adjusted": 220, "reason": "Distributed for insulin timing"}
    })

    card.update_step(4, [
        "Insulin timing: Take 15 min before meals",
        "Monitor CHO intake for dosing adjustments"
    ])

    card.update_step(5, {
        "protein": [{"food": "Beans"}, {"food": "Chicken"}, {"food": "Eggs"}],
        "fiber": [{"food": "Sukuma wiki"}, {"food": "Oranges"}]
    })

    print(card.format_for_display())
    print(f"\nCard complete: {card.is_complete()}")
    print(f"Should display: {ProfileSummaryCard.should_display_card('therapy')}")
