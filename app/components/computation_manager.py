from app.components.nutrient_calculator import (
    convert_fct_rows_to_foods,
    optimize_diet,
    greedy_allocation,
)
from app.components.dri_loader import DRILoader
import math
from typing import Dict, Any, List, Optional


class ComputationManager:
    """
    Central manager for all nutritional computations:
    - Energy + macronutrient estimation (Schofield/WHO)
    - Micronutrient targets (via DRI Loader)
    - Diet optimization (via NutrientCalculator)
    - Structured profile generation for retrieval/UI
    """

    def _init_(self, dri_table_path: str = "data/dri_table.csv"):
        self.dri = DRILoader(dri_table_path)

    # --------------------------------------------------------
    # 1️⃣ ENERGY + MACRONUTRIENT ESTIMATION
    # --------------------------------------------------------
    def estimate_energy_macros(
        self, age: int, sex: str, weight: float, height: float, activity_level: str
    ) -> Dict[str, Any]:
        sex = sex.upper()
        activity_factor = {
            "sedentary": 1.3,
            "light": 1.5,
            "moderate": 1.7,
            "active": 1.9,
        }.get(activity_level.lower(), 1.5)

        # Schofield BMR equations (kcal/day)
        if sex == "M":
            if age < 3:
                bmr = 60.9 * weight - 54
            elif age <= 10:
                bmr = 22.7 * weight + 495
            elif age <= 18:
                bmr = 17.5 * weight + 651
            else:
                bmr = 15.3 * weight + 679
        else:
            if age < 3:
                bmr = 61.0 * weight - 51
            elif age <= 10:
                bmr = 22.5 * weight + 499
            elif age <= 18:
                bmr = 12.2 * weight + 746
            else:
                bmr = 14.7 * weight + 496

        total_energy = bmr * activity_factor

        # Macronutrient distribution (DRI pattern)
        protein_pct, fat_pct, carb_pct = 0.15, 0.30, 0.55
        macros = {
            "calories": {
                "value": round(total_energy, 1),
                "unit": "kcal/day",
                "source": "WHO/FAO/UNU 2004 Energy Requirements",
                "citation": "Schofield Equation (1985)",
            },
            "protein": {
                "value": round(total_energy * protein_pct / 4, 1),
                "unit": "g/day",
                "source": "DRI Table E3.1.A4",
                "citation": "USDA Food Patterns 2020",
            },
            "fat": {
                "value": round(total_energy * fat_pct / 9, 1),
                "unit": "g/day",
                "source": "DRI Table E3.1.A4",
                "citation": "USDA Food Patterns 2020",
            },
            "carbohydrate": {
                "value": round(total_energy * carb_pct / 4, 1),
                "unit": "g/day",
                "source": "DRI Table E3.1.A4",
                "citation": "USDA Food Patterns 2020",
            },
        }
        return macros

    # --------------------------------------------------------
    # 2️⃣ MICRONUTRIENT TARGETS (via DRILoader)
    # --------------------------------------------------------
    def get_micronutrient_targets(self, age: int, sex: str) -> Dict[str, Any]:
        dri_values = self.dri.get_all_dri_for_group(age, sex)
        micronutrients = {}

        for nutrient, details in dri_values.items():
            parsed = details.get("value")
            if not parsed:
                continue

            display_val, approx_val = self._format_dri_value(parsed)
            if not display_val:
                continue

            micronutrients[nutrient] = {
                "display_value": display_val,
                "approx_value": approx_val,
                "unit": details.get("unit", ""),
                "source": details.get("source", "DRI Table E3.1.A4"),
                "citation": "USDA Nutritional Goals for Each Age/Sex Group (2020)",
            }

        return micronutrients

    # --------------------------------------------------------
    # Helper to normalize DRI structured values
    # --------------------------------------------------------
    def _format_dri_value(self, parsed: Dict[str, Any]) -> tuple[str, Optional[float]]:
        """
        Convert structured DRI value (with type/min/max) into display string and numeric approx.
        """
        if not parsed:
            return "", None

        t = parsed.get("type")
        if t == "range":
            return f"{parsed['min']}-{parsed['max']}", parsed["approx_value"]
        elif t in {"lt", "lt_eq"}:
            return f"<={parsed['max']}" if t == "lt_eq" else f"<{parsed['max']}", parsed["approx_value"]
        elif t in {"gt", "gt_eq"}:
            return f">={parsed['min']}" if t == "gt_eq" else f">{parsed['min']}", parsed["approx_value"]
        elif t == "eq":
            return str(parsed["min"]), parsed["approx_value"]
        else:
            return parsed.get("raw", ""), parsed.get("approx_value")

    # --------------------------------------------------------
    # 3️⃣ DIET OPTIMIZATION
    # --------------------------------------------------------
    def optimize_diet_plan(
        self,
        foods: List[Dict[str, Any]],
        targets: Dict[str, Any],
        allergies: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        foods_parsed = convert_fct_rows_to_foods(foods)
        if not foods_parsed:
            return {"error": "No valid food data available for optimization."}

        plan = optimize_diet(foods_parsed, targets, allergies=allergies)
        return plan

    # --------------------------------------------------------
    # 4️⃣ FULL PROFILE GENERATION
    # --------------------------------------------------------
    def generate_profile(
        self, age: int, sex: str, weight: float, height: float, activity_level: str
    ) -> Dict[str, Any]:
        energy_macros = self.estimate_energy_macros(age, sex, weight, height, activity_level)
        micronutrients = self.get_micronutrient_targets(age, sex)

        return {
            "metadata": {
                "age": age,
                "sex": sex,
                "weight": weight,
                "height": height,
                "activity_level": activity_level,
                "reference_docs": [
                    "DRI Table E3.1.A4",
                    "USDA Food Patterns (2020)",
                    "WHO/FAO/UNU Energy Requirements (2004)",
                ],
            },
            "energy_macros": energy_macros,
            "micronutrients": micronutrients,
            "summary": self._flatten_summary(energy_macros, micronutrients),
        }

    # --------------------------------------------------------
    # 5️⃣ UTILITY FLATTENER
    # --------------------------------------------------------
    def _flatten_summary(
        self, energy_macros: Dict[str, Any], micronutrients: Dict[str, Any]
    ) -> Dict[str, str]:
        flat = {}
        for k, v in energy_macros.items():
            flat[k.title()] = f"{v['value']} {v['unit']}"
        for k, v in micronutrients.items():
            flat[k] = f"{v['display_value']} {v['unit']}"
        return flat