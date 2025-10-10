# app/common/slot_schema.py
"""
Intent slot schemas for the Ambiguity Gate.
Each intent maps to a list of SlotSpec describing required fields, types and validation hints.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class SlotSpec:
    name: str
    type: str  # "string","enum","number","list","dict","bool"
    required: bool
    enum: Optional[List[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    hint: Optional[str] = None

SCHEMAS: Dict[str, List[SlotSpec]] = {
    "comparison": [
        SlotSpec("food_a", "string", True, hint="First food to compare"),
        SlotSpec("food_b", "string", True, hint="Second food to compare"),
        SlotSpec("food_state", "enum", True,
                 enum=["raw","boiled","fried","roasted","dried","fermented"],
                 hint="raw|boiled|fried|roasted|dried|fermented"),
        SlotSpec("basis", "enum", True, enum=["per_100g","per_serving"], hint="per_100g or per_serving"),
        SlotSpec("country", "string", True, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada")
    ],
    "recommendation": [
        SlotSpec("age", "number", True, min=0, max=120),
        SlotSpec("sex", "enum", True, enum=["male","female","other"]),
        SlotSpec("height_cm", "number", True, min=50, max=250),
        SlotSpec("weight_kg", "number", True, min=10, max=400),
        SlotSpec("country", "string", True, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada"),
        SlotSpec("goal", "enum", True,
                 enum=["weight_loss","maintenance","weight_gain","muscle_gain","general_health"]),
        SlotSpec("allergies", "list", True, hint="Food allergies, or ['none'] if no allergies")
    ],
    "therapy": [
        SlotSpec("diagnosis", "string", True, hint="Medical condition or diagnosis"),
        SlotSpec("age", "number", True, min=0, max=120, hint="Age in years"),
        SlotSpec("sex", "enum", True, enum=["male","female","other"], hint="Biological sex"),
        SlotSpec("weight_kg", "number", True, min=10, max=400, hint="Weight in kilograms"),
        SlotSpec("height_cm", "number", True, min=50, max=250, hint="Height in centimeters"),
        SlotSpec("medications", "list", False, hint="List of medications, or [] if none"),
        SlotSpec("key_biomarkers", "dict", False, hint="diagnosis-specific labs like eGFR, K+, HbA1c (optional)"),
        SlotSpec("country", "string", False, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada"),
        SlotSpec("allergies", "list", False, hint="Food allergies, or ['none'] if no allergies")
    ],
    "pregnancy": [
        SlotSpec("age", "number", True, min=12, max=55),
        SlotSpec("sex", "enum", True, enum=["female"]),
        SlotSpec("trimester", "enum", True, enum=["first","second","third"]),
        SlotSpec("country", "string", True, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada"),
        SlotSpec("allergies", "list", True, hint="Food allergies, or ['none'] if no allergies")
    ],
    "pediatric": [
        SlotSpec("age", "number", True, min=0, max=18),
        SlotSpec("weight_kg", "number", True, min=3, max=120),
        SlotSpec("country", "string", True, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada"),
        SlotSpec("allergies", "list", True, hint="Food allergies, or ['none'] if no allergies")
    ],
    "geriatrics": [
        SlotSpec("age", "number", True, min=60, max=120),
        SlotSpec("country", "string", True, hint="Country for FCT data, e.g., Nigeria, Kenya, Canada"),
        SlotSpec("allergies", "list", True, hint="Food allergies, or ['none'] if no allergies")
    ],
    "general": []
}