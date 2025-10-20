# app/components/computation_manager.py

from app.components.nutrient_calculator import NutrientCalculator
from app.components.dri_loader import DRILoader
import pandas as pd
import math


class ComputationManager:
    """
    Handles all nutritional computations:
    - Energy & macronutrient requirements
    - Micronutrient reference intakes
    - Integration with DRI table and nutrient calculator
    """

    def __init__(self, dri_table_path: str = "data/dri_table.csv"):
        # Load DRI reference data
        self.dri = DRILoader(dri_table_path)
        # Load nutrient calculator (for energy and ratios)
        self.calculator = NutrientCalculator()
        # Define pediatric-safe limits (fallbacks)
        self.default_age = 5
        self.default_sex = "F"

    # -------------------------------
    # 1️⃣ ENERGY & MACRONUTRIENTS
    # -------------------------------
    def compute_energy_macros(self, age: int, sex: str, weight: float, height: float, activity_level: str):
        """
        Estimate energy needs and macronutrient targets.
        Uses underlying NutrientCalculator logic (e.g. Schofield or WHO formulas).
        """
        try:
            result = self.calculator.calculate_energy_macros(
                age=age,
                sex=sex,
                weight=weight,
                height=height,
                activity_level=activity_level
            )
        except Exception as e:
            result = {"error": str(e)}
        return result

    # -------------------------------
    # 2️⃣ MICRONUTRIENT REFERENCE VALUES
    # -------------------------------
    def compute_micronutrient_targets(self, age: int, sex: str):
        """
        Fetch DRI-based micronutrient targets for a given age/sex group.
        """
        try:
            dri_values = self.dri.get_all_dri_for_group(age, sex)
            micronutrients = {}

            for nutrient, details in dri_values.items():
                if not details["value"]:
                    continue

                val = str(details["value"]).strip()
                if val.lower() in ["nan", ""]:
                    continue

                micronutrients[nutrient] = {
                    "recommended_intake": val,
                    "unit": details["unit"],
                    "source": details["source"]
                }
            return micronutrients

        except Exception as e:
            return {"error": f"DRI lookup failed: {e}"}

    # -------------------------------
    # 3️⃣ COMPREHENSIVE REQUIREMENTS REPORT
    # -------------------------------
    def generate_nutrition_profile(self, age: int, sex: str, weight: float, height: float, activity_level: str):
        """
        Combines energy + macro + micro computations into one structured output.
        Ideal for downstream presentation in chat or UI.
        """
        summary = {}

        # --- Energy and macros ---
        energy_data = self.compute_energy_macros(age, sex, weight, height, activity_level)
        summary["energy_macros"] = energy_data

        # --- Micronutrients (DRI lookup) ---
        micronutrient_data = self.compute_micronutrient_targets(age, sex)
        summary["micronutrients"] = micronutrient_data

        # --- Flatten for easy retrieval ---
        flat_summary = self._flatten_summary(summary)
        return {"summary": flat_summary, "raw": summary}

    # -------------------------------
    # 4️⃣ INTERNAL UTILITIES
    # -------------------------------
    def _flatten_summary(self, summary_dict):
        """
        Convert nested dicts into a flattened dict of readable strings.
        Useful for chat output and JSON serialization.
        """
        flat = {}

        if "energy_macros" in summary_dict:
            for k, v in summary_dict["energy_macros"].items():
                flat[f"{k.title()}"] = v

        if "micronutrients" in summary_dict:
            for nutrient, data in summary_dict["micronutrients"].items():
                val = data.get("recommended_intake", "N/A")
                unit = data.get("unit", "")
                flat[nutrient] = f"{val} {unit}".strip()

        return flat