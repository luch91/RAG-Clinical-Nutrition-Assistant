import re
from typing import Dict, Any, List
from app.common.logger import get_logger
logger = get_logger(__name__)

# ==============================
# West Africa country coverage
# ==============================
WEST_AFRICA_COUNTRIES = [
    "benin", "burkina faso", "gambia", "ghana",
    "guinea", "mali", "niger", "nigeria", "senegal"
]

# ==============================
# Country → File mapping
# ==============================
COUNTRY_FILE_MAP = {
    # Direct FCTs
    "kenya": "Kenya FCT.pdf",
    "uganda": "East n Central Uganda Food Composition Table.pdf",
    "south africa": "Food-based Dietary Guidelines South africa.pdf",
    "mozambique": "Food_composition_tables_for_Mozambique.pdf",
    "lesotho": "LESOTHO FCT.pdf",
    "malawi": "Malawian FCT.pdf",
    "canada": "Nutrient Value of Some Common Foods Canada.pdf",
    "india": "Indian Food Composition Table.pdf",
    "korea": "Korean_food_compositon_table_vol._2_7th__2006_.pdf",
    "tanzania": "tanzania_fct.pdf",
    "zimbabwe": "Zimbambwe.pdf",
    "congo": "Congo basin FCT.pdf",
    # Regional group
    "west africa": "Food Composition Table for West Africa 2019.PDF",
}

# ==============================
# Thematic source mapping (non-FCT)
# ==============================
SOURCE_PRIORITY_MAP = {
    "sports": ["Clinical Sports Nutrition.pdf"],
    "vegetarian": ["Plant-Based Nutrition in Clinical Practice 2022.epub"],
    "pediatric": [
        "Clinical Pediatric Dietetics.pdf",
        "Nutrition and Diet Therapy.pdf",
        "Clinical Nutrition.pdf"
    ],
    "pregnancy": ["Nutrition and Diet Therapy.pdf", "Clinical Nutrition.pdf"],
    "cancer": ["Clinical Nutrition.pdf", "Nutrition and Diet Therapy.pdf"],
    "geriatrics": ["Clinical Nutrition.pdf"],
    "autoimmune": ["Clinical Nutrition.pdf"],
    "therapy": ["Nutrition and Diet Therapy.pdf", "Clinical Nutrition.pdf"],
    "recommendation": ["Clinical Nutrition.pdf"],
    # Always include Human Biochemistry as a reasoning layer
    "biochem": ["Human Biochemistry.pdf"],
    # Skin & hair
    "skincare": ["Clinical Nutrition.pdf", "Nutrition and Diet Therapy.pdf"],
}

# ==============================
# Helper: Resolve country/region
# ==============================
def resolve_country_to_file(country: str) -> str:
    """
    Map country/region to the right FCT file if available.
    Handles country names and demonyms.
    """
    country = country.lower().strip()
    
    # Special handling for West Africa countries
    if country in WEST_AFRICA_COUNTRIES:
        return COUNTRY_FILE_MAP["west africa"]
    
    # Direct mapping
    return COUNTRY_FILE_MAP.get(country, None)

# ==============================
# Core: Build retrieval filters
# ==============================
def build_filters(template_key: str, slots: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build retrieval filters for vector search.
    Handles:
    - Country/region awareness
    - Missing-country clarifications
    - Disease-based filtering (extendable)
    - Thematic source prioritization
    """
    filters: Dict[str, Any] = {}
    clarification_needed = False
    clarification_options: List[str] = []
    prioritized_sources: List[str] = []
    
    # Country mapping - check both country and country_table slots
    country_slot = slots.get("country", "") or slots.get("country_table", "")
    if country_slot:
        # Strip version numbers (e.g., "Nigeria_2019" → "nigeria")
        country = re.sub(r'_\d{4}$', '', country_slot).lower().strip()
        mapped_file = resolve_country_to_file(country)
        
        if mapped_file:
            filters["country_table"] = mapped_file  # Store in country_table key for normalization
            logger.info(f"✅ Country '{country}' mapped to file: {mapped_file}")
        else:
            clarification_needed = True
            # Format options for user-friendly display (capitalize country names)
            all_countries = [c.capitalize() for c in COUNTRY_FILE_MAP.keys()] + [c.capitalize() for c in WEST_AFRICA_COUNTRIES]
            clarification_options = list(set(all_countries))
            logger.warning(f"⚠️ No dataset for '{country_slot}'. Clarification needed.")
    else:
        logger.info("ℹ️ No country specified in query slots. Using all sources.")
    
    # Disease/thematic mapping
    disease = slots.get("disease", "").lower() if slots.get("disease") else ""
    if disease:
        filters["disease"] = disease
        logger.info(f"ℹ️ Disease slot detected: {disease}")
    
    # Source prioritization by template
    if template_key in SOURCE_PRIORITY_MAP:
        prioritized_sources.extend(SOURCE_PRIORITY_MAP[template_key])
    
    # Always include Human Biochemistry for therapy & recommendation
    if template_key in ["therapy", "recommendation"] and "Human Biochemistry.pdf" not in prioritized_sources:
        prioritized_sources.append("Human Biochemistry.pdf")
    
    # Allergy-aware: pass allergies as an exclusion hint for downstream filtering
    if slots.get("allergies"):
        try:
            filters["exclude_allergens"] = [a.lower() for a in slots.get("allergies") if isinstance(a, str)]
        except Exception:
            filters["exclude_allergens"] = []
    
    return {
        "filters": filters,
        "clarification_needed": clarification_needed,
        "clarification_options": clarification_options,
        "prioritized_sources": prioritized_sources
    }

# ==============================
# Example usage
# ==============================
if __name__ == "__main__":
    test_slots = {"country": "Nigeria_2019"}
    print(build_filters("comparison", test_slots))
    test_slots2 = {"country": "Ethiopia"}
    print(build_filters("comparison", test_slots2))
    test_slots3 = {"disease": "diabetes"}
    print(build_filters("therapy", test_slots3))