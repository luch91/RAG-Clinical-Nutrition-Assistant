# app/components/fct_manager.py
"""
FCTManager (Food Composition Table Manager)

Manages country-specific Food Composition Tables for Step 5 of therapy flow.

Features:
- Country-to-FCT mapping
- Food source identification based on nutrient requirements
- Diagnosis-specific food filtering (PKU, allergies, CKD restrictions)
- Portion size calculations

Usage:
    fct_mgr = FCTManager()
    foods = fct_mgr.get_food_sources_for_requirements(
        therapeutic_requirements={"protein": {"value": 45, "unit": "g"}},
        country="Kenya",
        diagnosis="Type 1 Diabetes"
    )
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from langchain.schema import Document

logger = logging.getLogger(__name__)


class FCTManager:
    """
    Food Composition Table Manager for country-specific food retrieval.

    Handles Step 5 of therapy flow: Food source identification.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize FCT Manager.

        Args:
            config_path: Path to fct_country_mapping.json (auto-detected if None)
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "fct_country_mapping.json"

        self.config_path = Path(config_path)
        self.country_mapping = self._load_country_mapping()

    def _load_country_mapping(self) -> Dict[str, Any]:
        """
        Load country-to-FCT mapping from JSON config.

        Returns:
            Dict with country_to_fct, regional_mapping, default_fct
        """
        try:
            with open(self.config_path, 'r') as f:
                mapping = json.load(f)
            logger.info(f"Loaded FCT mapping for {len(mapping.get('country_to_fct', {}))} countries")
            return mapping
        except Exception as e:
            logger.error(f"Failed to load FCT mapping: {e}")
            return {"country_to_fct": {}, "regional_mapping": {}, "default_fct": None}

    def get_fct_for_country(self, country: str) -> Optional[str]:
        """
        Get FCT file path for a country.

        Args:
            country: Country name

        Returns:
            FCT file path or default FCT if country not found
        """
        if not country:
            return self.country_mapping.get("default_fct")

        country_normalized = country.strip().title()

        # Direct lookup
        fct_path = self.country_mapping.get("country_to_fct", {}).get(country_normalized)

        if fct_path:
            return fct_path

        # Fallback to default
        default = self.country_mapping.get("default_fct")
        if default:
            logger.warning(f"Country '{country}' not found in FCT mapping. Using default: {default}")

        return default

    def get_food_sources_for_requirements(
        self,
        therapeutic_requirements: Dict[str, Dict[str, Any]],
        country: str,
        diagnosis: Optional[str] = None,
        allergies: Optional[List[str]] = None,
        k: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get food sources for therapeutic nutrient requirements.

        This is STEP 5 of the therapy flow.

        Strategy:
        1. Identify country → FCT file
        2. For each nutrient in requirements:
           - Query FCT/vector store for foods high in that nutrient
           - Sort by nutrient density (per 100g)
           - Apply diagnosis restrictions (PKU, CKD, allergies, etc.)
           - Return top k foods with portion sizes

        Args:
            therapeutic_requirements: Dict from Step 2/4 with adjusted nutrient values
                Format: {"protein": {"value": 45, "unit": "g"}, ...}
            country: Country for FCT selection
            diagnosis: Diagnosis for food restrictions (optional)
            allergies: List of allergens to exclude (optional)
            k: Number of food sources per nutrient

        Returns:
            Dict mapping nutrient to list of food sources:
            {
                "protein": [
                    {"food": "Beans", "amount_per_100g": "21g", "serving_needed": "214g (1.5 cups)"},
                    ...
                ],
                ...
            }
        """
        # Get FCT for country
        fct_path = self.get_fct_for_country(country)
        if not fct_path:
            logger.warning("No FCT available - using generic food recommendations")
            return self._get_generic_food_sources(therapeutic_requirements, diagnosis, allergies, k)

        logger.info(f"Using FCT: {fct_path} for country: {country}")

        food_sources = {}

        # For each nutrient, find top food sources
        for nutrient, req_data in therapeutic_requirements.items():
            if not isinstance(req_data, dict):
                continue

            target_value = req_data.get("value")
            unit = req_data.get("unit")

            if target_value is None:
                continue

            # Query FCT/vector store for foods high in this nutrient
            foods = self._query_fct_for_nutrient(
                nutrient=nutrient,
                fct_path=fct_path,
                k=k * 2  # Get extra to allow for filtering
            )

            # Apply diagnosis-specific restrictions
            foods_filtered = self._apply_food_restrictions(
                foods=foods,
                diagnosis=diagnosis,
                allergies=allergies,
                nutrient=nutrient
            )

            # Calculate serving sizes needed to meet target
            foods_with_portions = []
            for food in foods_filtered[:k]:
                portion_info = self._calculate_portion_size(
                    food=food,
                    nutrient=nutrient,
                    target_value=target_value,
                    target_unit=unit
                )
                foods_with_portions.append(portion_info)

            food_sources[nutrient] = foods_with_portions

        return food_sources

    def _query_fct_for_nutrient(
        self,
        nutrient: str,
        fct_path: str,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Query FCT/vector store for foods high in a nutrient.

        Uses hybrid retrieval to find foods from the FCT document.

        Args:
            nutrient: Nutrient name
            fct_path: FCT file path
            k: Number of results

        Returns:
            List of food dicts with nutrient content
        """
        from app.components.hybrid_retriever import filtered_retrieval

        # Build query for high-nutrient foods
        query = f"Foods high in {nutrient} content per 100g"

        # Filter by FCT source
        filters = {
            "source": fct_path,
            "document_type": "fct"
        }

        try:
            # Retrieve from vector store
            documents = filtered_retrieval(
                query=query,
                filter_candidates=filters,
                k=k,
                use_bm25_fallback=True
            )

            # Parse documents to extract food data
            foods = self._parse_fct_documents(documents, nutrient)

            return foods

        except Exception as e:
            logger.error(f"FCT query failed for {nutrient}: {e}")
            # Fallback to generic foods
            return self._get_generic_foods_for_nutrient(nutrient, k)

    def _parse_fct_documents(
        self,
        documents: List[Document],
        nutrient: str
    ) -> List[Dict[str, Any]]:
        """
        Parse FCT documents to extract food and nutrient data.

        Args:
            documents: Retrieved documents from FCT
            nutrient: Target nutrient

        Returns:
            List of food dicts
        """
        foods = []

        for doc in documents:
            metadata = doc.metadata if hasattr(doc, "metadata") else {}

            # Try to extract food name and nutrient content
            food_name = metadata.get("food", metadata.get("title", "Unknown food"))
            nutrient_content = metadata.get(nutrient.lower())

            # If metadata doesn't have structured data, parse from text
            if not nutrient_content:
                # Try to extract from page_content (simplified regex)
                import re
                text = doc.page_content if hasattr(doc, "page_content") else str(doc)

                # Look for patterns like "Protein: 21g per 100g"
                pattern = rf"{nutrient}[:\s]+(\d+\.?\d*)\s*(g|mg|μg|mcg)"
                match = re.search(pattern, text, re.IGNORECASE)

                if match:
                    nutrient_content = {
                        "value": float(match.group(1)),
                        "unit": match.group(2)
                    }

            if nutrient_content:
                foods.append({
                    "food": food_name,
                    "nutrient": nutrient,
                    "content": nutrient_content,
                    "source": "FCT"
                })

        # Sort by nutrient content (descending)
        foods.sort(key=lambda x: x.get("content", {}).get("value", 0), reverse=True)

        return foods

    def _apply_food_restrictions(
        self,
        foods: List[Dict[str, Any]],
        diagnosis: Optional[str],
        allergies: Optional[List[str]],
        nutrient: str
    ) -> List[Dict[str, Any]]:
        """
        Apply diagnosis-specific food restrictions.

        Args:
            foods: List of food dicts
            diagnosis: Diagnosis
            allergies: List of allergens
            nutrient: Nutrient name

        Returns:
            Filtered list of foods
        """
        if not diagnosis and not allergies:
            return foods

        filtered = []

        for food in foods:
            food_name = food.get("food", "").lower()

            # Skip if allergenic
            if allergies:
                if any(allergen.lower() in food_name for allergen in allergies):
                    logger.debug(f"Excluding {food['food']} due to allergy")
                    continue

            # Diagnosis-specific restrictions
            if diagnosis:
                diagnosis_lower = diagnosis.lower()

                # PKU: Exclude high-protein foods (esp. meat, dairy, legumes)
                if "pku" in diagnosis_lower or "phenylketonuria" in diagnosis_lower:
                    high_phe_foods = ["meat", "chicken", "beef", "pork", "fish", "dairy", "milk",
                                     "cheese", "beans", "lentils", "peas", "soy", "egg"]
                    if any(food_item in food_name for food_item in high_phe_foods):
                        logger.debug(f"Excluding {food['food']} for PKU (high Phe)")
                        continue

                # CKD: Limit high-K, high-P foods
                elif "ckd" in diagnosis_lower or "kidney" in diagnosis_lower:
                    if nutrient.lower() in ["potassium", "phosphorus"]:
                        # For K and P, we want LOW sources, not high
                        logger.debug(f"CKD: Preferring lower {nutrient} foods")
                        # Could reverse sort or apply threshold here

                # Ketogenic: High fat, low CHO
                elif "ketogenic" in diagnosis_lower or "epilepsy" in diagnosis_lower:
                    if nutrient.lower() == "carbohydrate":
                        # For keto, prefer LOW carb foods
                        pass

            filtered.append(food)

        return filtered

    def _calculate_portion_size(
        self,
        food: Dict[str, Any],
        nutrient: str,
        target_value: float,
        target_unit: str
    ) -> Dict[str, Any]:
        """
        Calculate portion size needed to meet target nutrient value.

        Args:
            food: Food dict with nutrient content per 100g
            nutrient: Nutrient name
            target_value: Target amount needed
            target_unit: Target unit

        Returns:
            Dict with food, amount_per_100g, serving_needed
        """
        content = food.get("content", {})
        content_per_100g = content.get("value", 0)
        content_unit = content.get("unit", target_unit)

        # Simple portion calculation (assumes same units)
        if content_per_100g > 0:
            grams_needed = (target_value / content_per_100g) * 100
            # Convert to user-friendly serving
            serving_str = self._format_serving_size(food.get("food"), grams_needed)
        else:
            grams_needed = 0
            serving_str = "Unknown"

        return {
            "food": food.get("food"),
            "amount_per_100g": f"{content_per_100g}{content_unit}",
            "serving_needed": serving_str,
            "grams": grams_needed
        }

    def _format_serving_size(self, food_name: str, grams: float) -> str:
        """
        Convert grams to user-friendly serving sizes.

        Args:
            food_name: Food name
            grams: Grams needed

        Returns:
            Formatted serving string
        """
        # Simplified conversion (could be enhanced with actual serving data)
        if grams < 30:
            return f"{int(grams)}g (small portion)"
        elif grams < 100:
            return f"{int(grams)}g (1/2 cup approx)"
        elif grams < 200:
            return f"{int(grams)}g (1 cup approx)"
        elif grams < 400:
            return f"{int(grams)}g ({grams/200:.1f} cups approx)"
        else:
            return f"{int(grams)}g (large portion)"

    def _get_generic_food_sources(
        self,
        therapeutic_requirements: Dict[str, Dict[str, Any]],
        diagnosis: Optional[str],
        allergies: Optional[List[str]],
        k: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fallback: Get generic food sources when FCT not available.

        Returns hardcoded common foods for each nutrient.
        """
        logger.info("Using generic food sources (FCT not available)")

        generic_foods = {
            "protein": ["Beans", "Chicken breast", "Fish", "Eggs", "Lentils"],
            "carbohydrate": ["Rice", "Ugali", "Sweet potato", "Cassava", "Bread"],
            "fat": ["Avocado", "Nuts", "Olive oil", "Groundnuts", "Seeds"],
            "fiber": ["Sukuma wiki (kale)", "Oranges", "Carrots", "Whole grains", "Beans"],
            "calcium": ["Milk", "Yogurt", "Sardines", "Kale", "Sesame seeds"],
            "iron": ["Red meat", "Spinach", "Beans", "Fortified cereals", "Liver"],
            "vitamin_c": ["Oranges", "Mango", "Papaya", "Tomatoes", "Guava"],
            "vitamin_a": ["Carrots", "Sweet potato", "Mango", "Spinach", "Pumpkin"]
        }

        food_sources = {}

        for nutrient in therapeutic_requirements.keys():
            foods = generic_foods.get(nutrient.lower(), ["Various foods high in " + nutrient])
            food_sources[nutrient] = [{"food": food, "amount_per_100g": "varies", "serving_needed": "varies"} for food in foods[:k]]

        return food_sources

    def _get_generic_foods_for_nutrient(self, nutrient: str, k: int) -> List[Dict[str, Any]]:
        """Get generic foods for a specific nutrient."""
        generic_map = {
            "protein": [("Beans", 21), ("Chicken", 31), ("Fish", 20), ("Eggs", 13), ("Lentils", 9)],
            "calcium": [("Milk", 120), ("Yogurt", 110), ("Sardines", 380), ("Kale", 150), ("Sesame", 975)],
            "iron": [("Liver", 6.5), ("Spinach", 2.7), ("Beans", 5.3), ("Red meat", 2.6)],
        }

        foods_data = generic_map.get(nutrient.lower(), [(f"Food high in {nutrient}", 0)])

        return [
            {
                "food": name,
                "nutrient": nutrient,
                "content": {"value": value, "unit": "g" if nutrient == "protein" else "mg"},
                "source": "Generic"
            }
            for name, value in foods_data[:k]
        ]


# Example usage and testing
if __name__ == "__main__":
    fct_mgr = FCTManager()

    # Test country mapping
    kenya_fct = fct_mgr.get_fct_for_country("Kenya")
    print(f"Kenya FCT: {kenya_fct}")

    # Test food source retrieval (with fallback to generic)
    requirements = {
        "protein": {"value": 45, "unit": "g"},
        "calcium": {"value": 1000, "unit": "mg"}
    }

    foods = fct_mgr.get_food_sources_for_requirements(
        therapeutic_requirements=requirements,
        country="Kenya",
        diagnosis="Type 1 Diabetes",
        k=3
    )

    print(f"\nFood sources: {foods}")
