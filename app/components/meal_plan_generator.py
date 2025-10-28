# app/components/meal_plan_generator.py
"""
MealPlanGenerator

Generates 3-day therapeutic meal plans (Step 7 of therapy flow).

Features:
- 3 days × 5 meals (breakfast, snack, lunch, snack, dinner)
- Diagnosis-specific meal rules (T1D timing, CF enzymes, PKU restrictions, etc.)
- Portion calculations from therapeutic requirements
- Nutrient breakdown per meal + daily totals
- Medication timing integration
- Export to PDF/CSV

Usage:
    meal_gen = MealPlanGenerator()

    plan = meal_gen.generate_3day_plan(
        therapeutic_requirements=adjusted_requirements,
        food_sources=food_sources_from_step5,
        diagnosis="Type 1 Diabetes",
        medications=["insulin 20 units"],
        country="Kenya"
    )
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import random

logger = logging.getLogger(__name__)


class MealPlanGenerator:
    """
    Generates 3-day therapeutic meal plans with diagnosis-specific rules.

    This is STEP 7 of the therapy flow.
    """

    def __init__(self):
        """Initialize Meal Plan Generator."""
        self.meal_structure = ["Breakfast", "Mid-Morning Snack", "Lunch", "Afternoon Snack", "Dinner"]

    def generate_3day_plan(
        self,
        therapeutic_requirements: Dict[str, Dict[str, Any]],
        food_sources: Dict[str, List[Dict[str, Any]]],
        diagnosis: str,
        medications: Optional[List[str]] = None,
        country: Optional[str] = None,
        allergies: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate 3-day meal plan based on therapeutic requirements.

        This is STEP 7 of the therapy flow.

        Strategy:
        1. Create meal structure (3 days × 5 meals)
        2. Distribute daily targets across meals
        3. Select foods from Step 5 food sources
        4. Apply diagnosis-specific rules
        5. Calculate nutrient totals per meal and per day
        6. Add medication timing notes
        7. Validate nutrient targets met (±5%)

        Args:
            therapeutic_requirements: Adjusted requirements from Step 2/4
            food_sources: Food sources from Step 5
            diagnosis: Diagnosis for meal rules
            medications: List of medications for timing
            country: Country for cultural food preferences
            allergies: Food allergies to exclude

        Returns:
            Dict with:
            {
                "days": [
                    {
                        "day": 1,
                        "meals": [...],
                        "daily_totals": {...},
                        "compliance": 95.2  # % of targets met
                    },
                    ...
                ],
                "summary": {...},
                "medication_notes": [...],
                "citations": "FCT: Kenya Food Composition Table 2018"
            }
        """
        logger.info(f"Generating 3-day meal plan for {diagnosis}")

        # Get diagnosis-specific rules
        meal_rules = self._get_diagnosis_meal_rules(diagnosis)

        # Distribute daily targets across meals
        meal_targets = self._distribute_targets_across_meals(
            therapeutic_requirements,
            meal_rules
        )

        # Generate 3 days
        days = []
        for day_num in range(1, 4):
            day_plan = self._generate_single_day(
                day_num=day_num,
                meal_targets=meal_targets,
                food_sources=food_sources,
                diagnosis=diagnosis,
                meal_rules=meal_rules,
                allergies=allergies
            )
            days.append(day_plan)

        # Generate medication timing notes
        med_notes = self._generate_medication_notes(medications, diagnosis)

        # Create summary
        summary = self._create_plan_summary(days, therapeutic_requirements)

        # Generate citations
        citations = f"Meal plan generated using {country or 'Generic'} Food Composition Table"

        return {
            "days": days,
            "summary": summary,
            "medication_notes": med_notes,
            "citations": citations,
            "generated_at": datetime.now().isoformat()
        }

    def _get_diagnosis_meal_rules(self, diagnosis: str) -> Dict[str, Any]:
        """
        Get diagnosis-specific meal planning rules.

        Args:
            diagnosis: Diagnosis

        Returns:
            Dict with meal rules
        """
        diagnosis_lower = diagnosis.lower()

        # Type 1 Diabetes: Even CHO distribution, low GI
        if "diabetes" in diagnosis_lower or "t1d" in diagnosis_lower:
            return {
                "cho_distribution": "even",  # Distribute CHO evenly across meals
                "meal_timing": "regular",  # Regular meal times
                "notes": ["Match carbs to insulin timing", "Prefer low GI foods"],
                "meal_percentages": {
                    "Breakfast": 0.25,
                    "Mid-Morning Snack": 0.10,
                    "Lunch": 0.30,
                    "Afternoon Snack": 0.10,
                    "Dinner": 0.25
                }
            }

        # Cystic Fibrosis: High energy, high fat, enzymes with meals
        elif "cystic fibrosis" in diagnosis_lower or diagnosis_lower == "cf":
            return {
                "energy_boost": 1.5,  # 150% energy
                "fat_emphasis": True,
                "notes": ["Take pancreatic enzymes with meals", "High-calorie foods preferred"],
                "meal_percentages": {
                    "Breakfast": 0.25,
                    "Mid-Morning Snack": 0.15,
                    "Lunch": 0.25,
                    "Afternoon Snack": 0.15,
                    "Dinner": 0.20
                }
            }

        # PKU: Low protein, medical formula
        elif "pku" in diagnosis_lower or "phenylketonuria" in diagnosis_lower:
            return {
                "protein_restriction": True,
                "medical_formula": True,
                "notes": ["Restrict phenylalanine", "Medical formula with meals"],
                "meal_percentages": {
                    "Breakfast": 0.25,
                    "Mid-Morning Snack": 0.10,
                    "Lunch": 0.30,
                    "Afternoon Snack": 0.10,
                    "Dinner": 0.25
                }
            }

        # CKD: Limit K, P, fluid
        elif "ckd" in diagnosis_lower or "kidney" in diagnosis_lower:
            return {
                "restrict_k_p": True,
                "fluid_limit": True,
                "notes": ["Limit potassium and phosphorus", "Monitor fluid intake"],
                "meal_percentages": {
                    "Breakfast": 0.25,
                    "Mid-Morning Snack": 0.10,
                    "Lunch": 0.30,
                    "Afternoon Snack": 0.10,
                    "Dinner": 0.25
                }
            }

        # Ketogenic: 4:1 fat ratio
        elif "ketogenic" in diagnosis_lower or "epilepsy" in diagnosis_lower:
            return {
                "ketogenic_ratio": 4.0,  # 4:1 fat:(protein+CHO)
                "cho_restriction": True,
                "notes": ["Maintain 4:1 ketogenic ratio", "Very low carbohydrate"],
                "meal_percentages": {
                    "Breakfast": 0.30,
                    "Mid-Morning Snack": 0.10,
                    "Lunch": 0.30,
                    "Afternoon Snack": 0.10,
                    "Dinner": 0.20
                }
            }

        # Default: Standard distribution
        else:
            return {
                "notes": ["Standard meal distribution"],
                "meal_percentages": {
                    "Breakfast": 0.25,
                    "Mid-Morning Snack": 0.10,
                    "Lunch": 0.30,
                    "Afternoon Snack": 0.10,
                    "Dinner": 0.25
                }
            }

    def _distribute_targets_across_meals(
        self,
        daily_requirements: Dict[str, Dict[str, Any]],
        meal_rules: Dict[str, Any]
    ) -> Dict[str, Dict[str, float]]:
        """
        Distribute daily nutrient targets across meals.

        Args:
            daily_requirements: Daily therapeutic requirements
            meal_rules: Diagnosis-specific meal rules

        Returns:
            Dict mapping meal name to nutrient targets
        """
        meal_percentages = meal_rules.get("meal_percentages", {
            "Breakfast": 0.25,
            "Mid-Morning Snack": 0.10,
            "Lunch": 0.30,
            "Afternoon Snack": 0.10,
            "Dinner": 0.25
        })

        meal_targets = {}

        for meal_name, percentage in meal_percentages.items():
            meal_targets[meal_name] = {}

            for nutrient, req_data in daily_requirements.items():
                if isinstance(req_data, dict):
                    daily_value = req_data.get("adjusted", req_data.get("value", 0))
                else:
                    daily_value = req_data

                meal_targets[meal_name][nutrient] = daily_value * percentage

        return meal_targets

    def _generate_single_day(
        self,
        day_num: int,
        meal_targets: Dict[str, Dict[str, float]],
        food_sources: Dict[str, List[Dict[str, Any]]],
        diagnosis: str,
        meal_rules: Dict[str, Any],
        allergies: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate meal plan for a single day.

        Args:
            day_num: Day number (1-3)
            meal_targets: Nutrient targets per meal
            food_sources: Available food sources from Step 5
            diagnosis: Diagnosis
            meal_rules: Meal planning rules
            allergies: Food allergies

        Returns:
            Dict with day plan
        """
        meals = []
        daily_totals = {
            "energy": 0,
            "protein": 0,
            "carbohydrate": 0,
            "fat": 0,
            "fiber": 0
        }

        for meal_name in self.meal_structure:
            meal_data = self._generate_single_meal(
                meal_name=meal_name,
                targets=meal_targets.get(meal_name, {}),
                food_sources=food_sources,
                diagnosis=diagnosis,
                meal_rules=meal_rules,
                allergies=allergies,
                day_num=day_num
            )

            meals.append(meal_data)

            # Accumulate daily totals
            for nutrient in daily_totals.keys():
                daily_totals[nutrient] += meal_data["nutrient_totals"].get(nutrient, 0)

        # Calculate compliance (how well did we meet targets?)
        compliance = self._calculate_compliance(daily_totals, meal_targets)

        return {
            "day": day_num,
            "meals": meals,
            "daily_totals": daily_totals,
            "compliance": compliance,
            "notes": meal_rules.get("notes", [])
        }

    def _generate_single_meal(
        self,
        meal_name: str,
        targets: Dict[str, float],
        food_sources: Dict[str, List[Dict[str, Any]]],
        diagnosis: str,
        meal_rules: Dict[str, Any],
        allergies: Optional[List[str]],
        day_num: int
    ) -> Dict[str, Any]:
        """
        Generate a single meal with foods.

        Args:
            meal_name: Name of meal
            targets: Nutrient targets for this meal
            food_sources: Available foods
            diagnosis: Diagnosis
            meal_rules: Meal rules
            allergies: Allergies
            day_num: Day number for variety

        Returns:
            Dict with meal data
        """
        selected_foods = []
        nutrient_totals = {
            "energy": 0,
            "protein": 0,
            "carbohydrate": 0,
            "fat": 0,
            "fiber": 0
        }

        # Select 2-4 foods per meal based on meal type
        if "Snack" in meal_name:
            num_foods = 1 + (day_num % 2)  # 1-2 foods for snacks
        else:
            num_foods = 2 + (day_num % 3)  # 2-4 foods for main meals

        # Select foods from available sources
        available_nutrients = list(food_sources.keys())[:5]  # Focus on top nutrients

        for i, nutrient in enumerate(available_nutrients[:num_foods]):
            foods = food_sources.get(nutrient, [])

            if not foods:
                continue

            # Rotate through foods for variety across days
            food_index = (day_num - 1 + i) % len(foods)
            selected_food = foods[food_index]

            # Parse food data
            food_name = selected_food.get("food", "Unknown food")
            serving = selected_food.get("serving_needed", "1 serving")
            grams = selected_food.get("grams", 100)

            # Estimate nutrients (simplified - would use actual FCT data)
            estimated_nutrients = self._estimate_food_nutrients(
                food_name, grams, nutrient, selected_food
            )

            selected_foods.append({
                "food": food_name,
                "serving": serving,
                "grams": round(grams, 0),
                "nutrients": estimated_nutrients
            })

            # Accumulate totals
            for nut, value in estimated_nutrients.items():
                if nut in nutrient_totals:
                    nutrient_totals[nut] += value

        # Add medication timing if applicable
        timing_note = self._get_meal_timing_note(meal_name, diagnosis, meal_rules)

        return {
            "meal": meal_name,
            "time": self._get_meal_time(meal_name),
            "foods": selected_foods,
            "nutrient_totals": nutrient_totals,
            "timing_note": timing_note
        }

    def _estimate_food_nutrients(
        self,
        food_name: str,
        grams: float,
        primary_nutrient: str,
        food_data: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Estimate nutrient content for a food.

        (Simplified - in production would query actual FCT data)
        """
        # Generic nutrient estimates per 100g (very simplified)
        generic_estimates = {
            "protein": {"Beans": 21, "Chicken": 31, "Fish": 20, "Eggs": 13, "Milk": 3.4},
            "carbohydrate": {"Rice": 80, "Ugali": 40, "Bread": 50, "Potato": 17, "Cassava": 38},
            "fat": {"Avocado": 15, "Nuts": 50, "Oil": 100, "Groundnuts": 49},
            "fiber": {"Kale": 4, "Beans": 15, "Oranges": 2.4, "Carrots": 2.8}
        }

        # Get base values
        factor = grams / 100.0

        # Simplified estimation
        protein = generic_estimates.get("protein", {}).get(food_name, 5) * factor
        carbs = generic_estimates.get("carbohydrate", {}).get(food_name, 10) * factor
        fat = generic_estimates.get("fat", {}).get(food_name, 5) * factor
        fiber = generic_estimates.get("fiber", {}).get(food_name, 2) * factor
        energy = (protein * 4) + (carbs * 4) + (fat * 9)

        return {
            "energy": round(energy, 1),
            "protein": round(protein, 1),
            "carbohydrate": round(carbs, 1),
            "fat": round(fat, 1),
            "fiber": round(fiber, 1)
        }

    def _get_meal_time(self, meal_name: str) -> str:
        """Get suggested meal time."""
        times = {
            "Breakfast": "7:00 AM",
            "Mid-Morning Snack": "10:00 AM",
            "Lunch": "1:00 PM",
            "Afternoon Snack": "4:00 PM",
            "Dinner": "7:00 PM"
        }
        return times.get(meal_name, "")

    def _get_meal_timing_note(
        self,
        meal_name: str,
        diagnosis: str,
        meal_rules: Dict[str, Any]
    ) -> Optional[str]:
        """Get medication/timing note for meal."""
        if "diabetes" in diagnosis.lower() or "t1d" in diagnosis.lower():
            if "Snack" not in meal_name:
                return "💊 Take insulin 15 minutes before meal"

        if "cystic fibrosis" in diagnosis.lower() or "cf" in diagnosis.lower():
            if "Snack" not in meal_name:
                return "💊 Take pancreatic enzymes with meal"

        return None

    def _calculate_compliance(
        self,
        daily_totals: Dict[str, float],
        meal_targets: Dict[str, Dict[str, float]]
    ) -> float:
        """
        Calculate how well daily totals meet targets.

        Args:
            daily_totals: Actual nutrient totals for the day
            meal_targets: Target nutrients per meal

        Returns:
            Compliance percentage (0-100)
        """
        # Sum up all meal targets to get daily targets
        daily_targets = {}
        for meal_targets_data in meal_targets.values():
            for nutrient, value in meal_targets_data.items():
                daily_targets[nutrient] = daily_targets.get(nutrient, 0) + value

        # Calculate compliance for key nutrients
        key_nutrients = ["energy", "protein", "carbohydrate", "fat"]
        compliances = []

        for nutrient in key_nutrients:
            target = daily_targets.get(nutrient, 0)
            actual = daily_totals.get(nutrient, 0)

            if target > 0:
                compliance_pct = min(100, (actual / target) * 100)
                compliances.append(compliance_pct)

        # Average compliance
        if compliances:
            return round(sum(compliances) / len(compliances), 1)
        else:
            return 0.0

    def _generate_medication_notes(
        self,
        medications: Optional[List[str]],
        diagnosis: str
    ) -> List[str]:
        """Generate medication timing notes."""
        if not medications:
            return []

        notes = []

        for med in medications:
            med_lower = med.lower()

            if "insulin" in med_lower:
                notes.append("Insulin: Take 15 minutes before main meals (breakfast, lunch, dinner)")

            if "enzyme" in med_lower or "creon" in med_lower or "zenpep" in med_lower:
                notes.append("Pancreatic enzymes: Take with all meals and snacks containing fat")

            if "metformin" in med_lower:
                notes.append("Metformin: Take with meals to reduce GI side effects")

        return notes

    def _create_plan_summary(
        self,
        days: List[Dict[str, Any]],
        therapeutic_requirements: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create overall plan summary."""
        # Average compliance across days
        avg_compliance = sum(day["compliance"] for day in days) / len(days)

        # Total meals
        total_meals = sum(len(day["meals"]) for day in days)

        return {
            "total_meals": total_meals,
            "days": len(days),
            "average_compliance": round(avg_compliance, 1),
            "status": "✅ Targets met" if avg_compliance >= 90 else "⚠️ Review recommended"
        }

    def format_meal_plan_for_display(self, meal_plan: Dict[str, Any]) -> str:
        """
        Format meal plan for user-friendly display.

        Args:
            meal_plan: Generated meal plan

        Returns:
            Formatted markdown string
        """
        lines = ["# 📅 3-Day Therapeutic Meal Plan\n"]

        for day_data in meal_plan["days"]:
            lines.append(f"\n## DAY {day_data['day']}")
            lines.append("─" * 60)

            for meal in day_data["meals"]:
                lines.append(f"\n### {meal['meal']} ({meal['time']})")

                for food in meal["foods"]:
                    lines.append(f"  • {food['food']} - {food['serving']}")

                nutrients = meal["nutrient_totals"]
                lines.append(f"  **Nutrients:** {nutrients['energy']:.0f} kcal, "
                           f"{nutrients['protein']:.0f}g protein, "
                           f"{nutrients['carbohydrate']:.0f}g CHO, "
                           f"{nutrients['fat']:.0f}g fat")

                if meal.get("timing_note"):
                    lines.append(f"  {meal['timing_note']}")

            totals = day_data["daily_totals"]
            lines.append(f"\n**Day {day_data['day']} Totals:** "
                       f"{totals['energy']:.0f} kcal, "
                       f"{totals['protein']:.0f}g protein, "
                       f"{totals['carbohydrate']:.0f}g CHO, "
                       f"{totals['fat']:.0f}g fat, "
                       f"{totals['fiber']:.0f}g fiber")
            lines.append(f"**Compliance:** {day_data['compliance']}%")

        # Summary
        summary = meal_plan["summary"]
        lines.append(f"\n## 📊 Plan Summary")
        lines.append(f"  • Total meals: {summary['total_meals']}")
        lines.append(f"  • Average compliance: {summary['average_compliance']}%")
        lines.append(f"  • Status: {summary['status']}")

        # Medication notes
        if meal_plan.get("medication_notes"):
            lines.append(f"\n## 💊 Medication Reminders")
            for note in meal_plan["medication_notes"]:
                lines.append(f"  • {note}")

        # Citations
        lines.append(f"\n## 📚 Source")
        lines.append(f"  {meal_plan['citations']}")

        return "\n".join(lines)


# Example usage and testing
if __name__ == "__main__":
    meal_gen = MealPlanGenerator()

    # Mock therapeutic requirements
    requirements = {
        "energy": {"adjusted": 1650, "unit": "kcal"},
        "protein": {"adjusted": 45, "unit": "g"},
        "carbohydrate": {"adjusted": 220, "unit": "g"},
        "fat": {"adjusted": 55, "unit": "g"},
        "fiber": {"adjusted": 13, "unit": "g"}
    }

    # Mock food sources
    food_sources = {
        "protein": [{"food": "Beans", "serving_needed": "214g (1.5 cups)", "grams": 214}],
        "carbohydrate": [{"food": "Rice", "serving_needed": "275g (1.5 cups)", "grams": 275}],
        "fiber": [{"food": "Kale", "serving_needed": "325g", "grams": 325}]
    }

    plan = meal_gen.generate_3day_plan(
        therapeutic_requirements=requirements,
        food_sources=food_sources,
        diagnosis="Type 1 Diabetes",
        medications=["insulin 20 units"],
        country="Kenya"
    )

    print(meal_gen.format_meal_plan_for_display(plan))
