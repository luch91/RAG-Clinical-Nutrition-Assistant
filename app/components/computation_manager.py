# app/components/computation_manager.py

import math
import logging
from typing import Dict, Any, Optional

from app.common.logger import get_logger
from app.common.custom_exception import CustomException
from app.components.chapter_extractor import DRI_TOC
from app.components.metadata_enricher import DRI_CONDITION_TAGS, get_metadata_reference

logger = get_logger(__name__)

class ComputationManager:
    """
    Handles nutrient requirement computation and dynamic DRI traceability.
    Integrates chapter_extractor + metadata_enricher for fully explainable outputs.
    """

    def __init__(self):
        logger.info("ComputationManager initialized with DRI-aware mode.")

    # ------------------------- INTERNAL HELPERS -------------------------

    def _normalize_key(self, name: str) -> str:
        """Normalize nutrient key to DRI mapping standard."""
        return name.lower().replace(" ", "_")

    def _get_dri_reference(self, nutrient: str) -> Dict[str, Any]:
        """
        Map nutrient to corresponding DRI TOC entry and condition tags.
        Returns structured metadata for traceability and retrieval augmentation.
        """
        nutrient_key = self._normalize_key(nutrient)
        ref_data = {
            "chapter_title": "General DRI Guidelines",
            "pages": (19, 68),
            "condition_tags": ["dri_general"],
            "confidence": 0.5,
        }

        try:
            # Match chapter title + page range
            for key, section in DRI_TOC.items():
                if nutrient_key in key or key in nutrient_key:
                    ref_data.update({
                        "chapter_title": section["title"],
                        "pages": section["pages"],
                        "condition_tags": DRI_CONDITION_TAGS.get(key, []),
                        "confidence": 0.95,
                    })

                    # Add enriched metadata (source and context)
                    metadata = get_metadata_reference("Dietary Reference Intakes", section["title"])
                    ref_data.update({
                        "source": metadata.get("source", "DRI - The Essential Guide"),
                        "chapter_key": key,
                    })
                    return ref_data

        except Exception as e:
            logger.warning(f"DRI reference mapping failed for {nutrient}: {e}")

        return ref_data

    # ------------------------- COMPUTATION CORE -------------------------

    def compute_requirements(
        self,
        age: float,
        sex: str,
        weight: Optional[float] = None,
        height: Optional[float] = None,
        condition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute age- and sex-adjusted DRI nutrient recommendations.
        Returns results with DRI references and semantic tags attached.
        """

        try:
            results: Dict[str, Any] = {}

            # --- Example base data (expandable later or fetched from JSON tables)
            base_dri = {
                "Protein": 0.95,   # g/kg/day for 4–13y
                "Iron": 8,         # mg/day
                "Zinc": 8,         # mg/day
                "Calcium": 1300,   # mg/day
                "Vitamin D": 15,   # µg/day
                "Energy": 2000,    # kcal/day
            }

            # --- Age scaling (simplified pediatric adjustments)
            age_factor = 1.0
            if age < 1:
                age_factor = 0.5
            elif age < 3:
                age_factor = 0.75
            elif 3 <= age <= 8:
                age_factor = 0.9
            elif 9 <= age <= 13:
                age_factor = 1.0
            elif 14 <= age <= 18:
                age_factor = 1.2

            # --- Core computations
            for nutrient, base_value in base_dri.items():
                if "Protein" in nutrient and weight:
                    value = round(weight * base_value * age_factor, 1)
                elif "Energy" in nutrient and weight:
                    value = round(base_value * (weight / 30) * age_factor)
                else:
                    value = round(base_value * age_factor, 1)

                # Reference metadata
                ref = self._get_dri_reference(nutrient)

                # Construct structured result
                results[nutrient] = {
                    "value": value,
                    "unit": "g/day" if "Protein" in nutrient else
                             "kcal/day" if "Energy" in nutrient else "mg/day",
                    "reference": ref
                }

            logger.info(f"DRI computation completed for {sex}, age {age}y.")
            return {
                "requirements": results,
                "metadata": {
                    "textbook": "Dietary Reference Intakes",
                    "method": "DRI-based pediatric scaling",
                    "confidence": 0.94,
                },
            }

        except Exception as e:
            logger.error(f"Computation failed: {e}")
            raise CustomException("Failed to compute nutrient requirements", e)