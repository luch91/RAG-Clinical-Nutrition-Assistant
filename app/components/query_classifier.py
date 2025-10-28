import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import os
import re
from app.config.config import DISTILBERT_CLASSIFIER_PATH
import logging
from typing import Optional, Dict, Any, List
from app.common.custom_exception import CustomException

logger = logging.getLogger(__name__)

# Supported therapy conditions (from llm_response_manager.py)
SUPPORTED_THERAPY_CONDITIONS = {
    "preterm nutrition": "Preterm Nutrition",
    "type 1 diabetes": "Type 1 Diabetes",
    "t1d": "Type 1 Diabetes",
    "food allergy": "Food Allergy",
    "cystic fibrosis": "Cystic Fibrosis",
    "cf": "Cystic Fibrosis",
    "pku": "PKU",
    "phenylketonuria": "PKU",
    "msud": "MSUD",
    "maple syrup urine disease": "MSUD",
    "galactosemia": "Galactosemia",
    "epilepsy": "Epilepsy",
    "ketogenic therapy": "Epilepsy / Ketogenic Therapy",
    "chronic kidney disease": "Chronic Kidney Disease",
    "ckd": "Chronic Kidney Disease",
    "gi disorders": "GI Disorders",
    "ibd": "GI Disorders",
    "inflammatory bowel disease": "GI Disorders",
    "gerd": "GI Disorders",
    "gastroesophageal reflux": "GI Disorders"
}

# Ensure Windows path compatibility
MODEL_PATH = os.path.normpath(DISTILBERT_CLASSIFIER_PATH)

# Biomarkers list (must match training data)
BIOMARKERS = [
    'creatinine', 'HbA1c', 'ferritin', 'urea',
    'albumin', 'glucose', 'zinc', 'iron', 'protein', 'fiber',
    'calcium', 'phytate', 'potassium', 'sodium', 'magnesium',
    'phosphorus', 'cholesterol', 'triglycerides', 'bilirubin',
    'egfr', 'ldl', 'hemoglobin', 'transferrin', 'alt', 'tsh',
    'ammonia', 'leucine', 'phenylalanine', 'vitamin_d', 'vitamin_b12',
    'vitamin_a', 'vitamin_k', 'vitamin_e', 'folate'
]

# Medications list (extracted from Drug-Nutrient Interactions TOC + common pediatric meds)
MEDICATIONS = [
    # Antiepileptics (AED) - Critical for epilepsy therapy
    'phenytoin', 'phenobarbital', 'carbamazepine', 'valproate', 'valproic acid',
    'lamotrigine', 'levetiracetam', 'topiramate',

    # Diabetes medications
    'insulin', 'metformin', 'sulfonylureas', 'glipizide', 'glyburide',

    # Antibiotics (common in CF, infections)
    'rifampin', 'isoniazid', 'tetracycline', 'doxycycline', 'fluoroquinolones',
    'ciprofloxacin', 'azithromycin', 'amoxicillin',

    # Immunosuppressants (transplant, IBD)
    'cyclosporine', 'tacrolimus', 'sirolimus', 'mycophenolate', 'azathioprine',

    # Corticosteroids (CF, IBD, asthma)
    'prednisone', 'prednisolone', 'dexamethasone', 'hydrocortisone', 'budesonide',

    # Cardiac drugs (CHD)
    'digoxin', 'furosemide', 'spironolactone', 'enalapril', 'captopril',

    # Proton pump inhibitors (GERD, gastroparesis)
    'omeprazole', 'lansoprazole', 'pantoprazole', 'esomeprazole',

    # H2 blockers
    'ranitidine', 'famotidine', 'cimetidine',

    # Chemotherapy (oncology)
    'methotrexate', 'cisplatin', '6-mercaptopurine',

    # Diuretics (CKD, heart failure)
    'furosemide', 'thiazide', 'hydrochlorothiazide',

    # NSAIDs
    'ibuprofen', 'naproxen', 'aspirin',

    # Other important pediatric drugs
    'sulfasalazine', 'mesalamine', 'infliximab', 'adalimumab',
    'pancreatic enzymes', 'creon', 'zenpep',  # CF specific
    'penicillamine', 'allopurinol', 'colchicine'
]

class NutritionQueryClassifier:
    def __init__(self, model_path: str = MODEL_PATH):
        try:
            logger.info(f"Loading classifier model from: {model_path}")
            # Verify model path exists
            if not os.path.exists(model_path):
                logger.error(f"Model path does not exist: {model_path}")
                raise CustomException(f"Classifier model not found at {model_path}", None)
            
            # Load tokenizer and model
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
            self.model.eval()
            
            # Label mapping should match your training
            self.id2label = {
                0: "comparison",
                1: "recommendation",
                2: "therapy",
                3: "general"
            }
            self.label2id = {v: k for k, v in self.id2label.items()}
            
            logger.info("✅ Classifier loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load classifier: {str(e)}")
            raise CustomException("Classifier initialization failed", e)

    def preprocess_with_biomarker_tags(self, text: str) -> str:
        """
        Apply biomarker-aware preprocessing with [BIOMARKER] tags.
        CRITICAL: Must match training preprocessing exactly.
        """
        modified_text = text
        for bm in BIOMARKERS:
            # Use whitespace boundaries (not \\b which breaks on HbA1c)
            left = r'(^|\s)'
            escaped_bm = re.escape(bm)
            value = r'(?:\s*[\d.,]+\s*\%)?'  # Optional value with %
            right = r'(?=\s|$)'
            pattern = left + escaped_bm + value + right

            # Wrap biomarkers with special tokens
            modified_text = re.sub(
                pattern,
                r'\g<1>[BIOMARKER]\g<0>[/BIOMARKER]',  # \g<1> = leading space, \g<0> = full match
                modified_text,
                flags=re.IGNORECASE
            )

        return modified_text

    def extract_medications(self, query: str) -> list:
        """
        Extract medication names from query.
        Uses keyword matching with medication list.
        """
        medications = []
        query_lower = query.lower()

        for med in MEDICATIONS:
            # Check for medication mentions
            if med.lower() in query_lower:
                medications.append(med)

        # Remove duplicates while preserving order
        medications = list(dict.fromkeys(medications))

        return medications

    def enforce_gatekeeper(self, query: str, label: str, confidence: float) -> str:
        """
        Gatekeeper logic that enforces classification downgrades
        based on confidence and content mismatch.
        """
        q = query.lower()

        # 1️⃣ Low confidence downgrade
        if confidence < 0.60:
            logger.warning(f"⚠️ Very low confidence ({confidence:.2f}) — downgrading to 'general'")
            return "general"

        # 2️⃣ Therapy downgrade — model must be certain and query must sound clinical
        if label == "therapy":
            if confidence < 0.78:
                logger.warning(f"⚠️ Therapy prediction below threshold ({confidence:.2f}) — downgrading to 'recommendation'")
                return "recommendation"

            if not any(word in q for word in ["therapy", "treatment", "disease", "diagnosed", "patient", "has", "ckd", "diabetes", "epilepsy"]):
                logger.warning("⚠️ Query lacks clinical indicators — forcing downgrade to 'recommendation'")
                return "recommendation"

        # 3️⃣ Comparison downgrade if structure mismatch
        if label == "comparison" and not re.search(r'\b(vs|compare|difference|between|than)\b', q):
            logger.info("ℹ️ Lacking comparison cue — downgraded to 'general'")
            return "general"

        # 4️⃣ Recommendation sanity check
        if label == "recommendation" and not any(x in q for x in ["recommend", "should i", "what to eat", "how much", "diet plan", "meal plan"]):
            if confidence < 0.7:
                return "general"

        return label


    def classify(self, query: str) -> dict:
        """Return classification with clinical safety checks"""
        try:
            # CRITICAL: Apply biomarker tag preprocessing (must match training)
            preprocessed_query = self.preprocess_with_biomarker_tags(query)

            # Tokenize input with biomarker tags
            inputs = self.tokenizer(
                preprocessed_query,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=512
            )
            
            # Get model predictions
            with torch.no_grad():
                outputs = self.model(**inputs)
                pred = torch.argmax(outputs.logits, dim=1).item()
                confidence = torch.softmax(outputs.logits, dim=1)[0][pred].item()
            
            label = self.id2label[pred]
            
            # CRITICAL: Safety check for therapy queries
            if label == "therapy" and confidence < 0.75:
                logger.warning("⚠️ Low-confidence therapy classification - defaulting to recommendation")
                label = "recommendation"
            
            # Extract biomarkers with detailed values
            biomarkers_detailed = self.extract_biomarkers_with_values(query)
            biomarker_names = list(biomarkers_detailed.keys())

            # Rule-based enhancements
            result = {
                "label": label,
                "diagnosis": self._extract_diagnosis(query),  # Extract diagnosis from query
                "biomarkers": biomarker_names,  # List of names for backward compatibility
                "biomarkers_detailed": biomarkers_detailed,  # Dict with values/units
                "medications": self.extract_medications(query),
                "needs_followup": self._needs_followup(label, query),
                "is_high_risk": self.detect_high_risk(query),
                "confidence": confidence,
                "complexity": self.estimate_complexity(query, label),
                "country": self._extract_country(query)
            }
            return result
        except Exception as e:
            logger.error(f"❌ Classification failed: {str(e)}")
            # Fallback to safe defaults with explicit safety checks
            return {
                "label": "general",
                "diagnosis": None,
                "biomarkers": [],
                "biomarkers_detailed": {},
                "medications": [],
                "needs_followup": False,
                "is_high_risk": False,
                "confidence": 0.0,
                "complexity": 2,
                "country": None,
                "error": str(e)
            }
    
    def _needs_followup(self, label: str, query: str) -> bool:
        """Determine if follow-up questions are needed"""
        # Always need follow-up for therapy and recommendation
        if label in ["therapy", "recommendation"]:
            return True
        
        # For comparison, check if specific preparation methods are mentioned
        if label == "comparison":
            prep_methods = ["raw", "boiled", "fermented", "soaked", "dry"]
            return not any(method in query.lower() for method in prep_methods)
        
        return False
    
    def extract_biomarkers(self, query: str) -> list:
        """
        Detect clinical biomarkers in the query with values and units.
        Returns list of biomarker names for backward compatibility.
        Use extract_biomarkers_with_values() for detailed extraction.
        """
        biomarkers_dict = self.extract_biomarkers_with_values(query)
        return list(biomarkers_dict.keys())

    def _validate_biomarker_value(self, biomarker: str, value: float, unit: str) -> dict:
        """
        Validate biomarker values against physiological ranges.
        Returns: {"valid": bool, "warning": str or None, "severity": "impossible"|"critical"|"warning"|None}
        """
        # Define physiological ranges (min, max, critical_low, critical_high)
        # Format: (absolute_min, absolute_max, critical_low, critical_high)
        ranges = {
            "hba1c": (0.1, 20.0, 3.0, 14.0) if unit == "%" else (1, 200, 20, 140),  # % or mmol/mol
            "glucose": (10, 1000, 40, 500) if unit == "mg/dL" else (0.5, 55, 2.2, 27.8),  # mg/dL or mmol/L
            "creatinine": (0.01, 30.0, 0.2, 15.0) if unit == "mg/dL" else (1, 2655, 18, 1327),  # mg/dL or µmol/L
            "albumin": (0.1, 6.0, 1.5, 5.5) if unit == "g/dL" else (1, 60, 15, 55),  # g/dL or g/L
            "hemoglobin": (0.5, 25.0, 5.0, 20.0) if unit == "g/dL" else (5, 250, 50, 200),  # g/dL or g/L
            "potassium": (0.5, 10.0, 2.0, 8.0),  # mEq/L or mmol/L
            "sodium": (80, 200, 120, 160),  # mEq/L or mmol/L
            "calcium": (2.0, 15.0, 6.0, 13.0) if unit == "mg/dL" else (0.5, 3.75, 1.5, 3.25),  # mg/dL or mmol/L
            "egfr": (1, 200, 5, 150),  # mL/min/1.73m²
            "urea": (1, 300, 5, 200) if unit == "mg/dL" else (0.5, 107, 1.8, 71.4),  # mg/dL or mmol/L
            "ferritin": (0.1, 10000, 5, 1500),  # ng/mL
            "alt": (1, 5000, 5, 1000),  # U/L
            "tsh": (0.01, 100, 0.1, 20),  # mIU/L
            "ammonia": (1, 1000, 10, 500),  # µmol/L
            "triglycerides": (10, 5000, 30, 1000) if unit == "mg/dL" else (0.1, 56.5, 0.34, 11.3),  # mg/dL or mmol/L
            "ldl": (10, 500, 20, 300) if unit == "mg/dL" else (0.26, 12.9, 0.52, 7.76),  # mg/dL or mmol/L
        }

        # CRITICAL FIX: Unit-sensitive ranges for biomarkers with different unit systems
        # These need special handling because the same biomarker has different ranges depending on unit
        if biomarker == "creatinine":
            if unit in ["mg/dL", "mg/dl"]:
                abs_min, abs_max, crit_low, crit_high = (0.01, 30.0, 0.2, 15.0)
            elif unit == "µmol/L":
                abs_min, abs_max, crit_low, crit_high = (1, 2655, 18, 1327)
            else:  # default to mg/dL
                abs_min, abs_max, crit_low, crit_high = (0.01, 30.0, 0.2, 15.0)
        elif biomarker == "albumin":
            if unit in ["g/dL", "g/dl"]:
                abs_min, abs_max, crit_low, crit_high = (0.1, 6.0, 1.5, 5.5)
            elif unit == "g/L":
                abs_min, abs_max, crit_low, crit_high = (1, 60, 15, 55)
            else:  # default to g/dL
                abs_min, abs_max, crit_low, crit_high = (0.1, 6.0, 1.5, 5.5)
        elif biomarker == "hemoglobin":
            if unit in ["g/dL", "g/dl"]:
                abs_min, abs_max, crit_low, crit_high = (0.5, 25.0, 5.0, 20.0)
            elif unit == "g/L":
                abs_min, abs_max, crit_low, crit_high = (5, 250, 50, 200)
            else:  # default to g/dL
                abs_min, abs_max, crit_low, crit_high = (0.5, 25.0, 5.0, 20.0)
        elif biomarker == "hba1c":
            if unit == "%":
                abs_min, abs_max, crit_low, crit_high = (0.1, 20.0, 3.0, 14.0)
            elif unit == "mmol/mol":
                abs_min, abs_max, crit_low, crit_high = (1, 200, 20, 140)
            else:  # default to %
                abs_min, abs_max, crit_low, crit_high = (0.1, 20.0, 3.0, 14.0)
        elif biomarker == "glucose":
            if unit in ["mg/dL", "mg/dl"]:
                abs_min, abs_max, crit_low, crit_high = (10, 1000, 40, 500)
            elif unit == "mmol/L":
                abs_min, abs_max, crit_low, crit_high = (0.5, 55, 2.2, 27.8)
            else:  # default to mg/dL
                abs_min, abs_max, crit_low, crit_high = (10, 1000, 40, 500)
        elif biomarker in ranges:
            # For other biomarkers, use the predefined ranges
            abs_min, abs_max, crit_low, crit_high = ranges[biomarker]
        else:
            # Unknown biomarker - no validation
            return {"valid": True, "warning": None, "severity": None}

        # Check impossible values
        if value <= 0:
            return {
                "valid": False,
                "warning": f"{biomarker.upper()} cannot be zero or negative (got {value} {unit})",
                "severity": "impossible"
            }

        if value < abs_min or value > abs_max:
            return {
                "valid": False,
                "warning": f"{biomarker.upper()} {value} {unit} is physiologically impossible (range: {abs_min}-{abs_max} {unit})",
                "severity": "impossible"
            }

        # Check critical values (dangerous but possible)
        if value < crit_low:
            return {
                "valid": True,
                "warning": f"{biomarker.upper()} {value} {unit} is critically LOW (typical minimum: {crit_low} {unit})",
                "severity": "critical"
            }

        if value > crit_high:
            return {
                "valid": True,
                "warning": f"{biomarker.upper()} {value} {unit} is critically HIGH (typical maximum: {crit_high} {unit})",
                "severity": "critical"
            }

        # Value is within acceptable range
        return {"valid": True, "warning": None, "severity": None}

    def extract_biomarkers_with_values(self, query: str) -> dict:
        """
        Extract biomarkers with their values and units.
        NOW WITH VALIDATION: Rejects impossible values, flags dangerous ones.

        Returns:
            {
                "creatinine": {"value": 2.1, "unit": "mg/dL", "raw": "creatinine 2.1 mg/dL", "validation": {...}},
                "HbA1c": {"value": 8.5, "unit": "%", "raw": "HbA1c 8.5%"}
            }
        """
        biomarkers = {}
        query_lower = query.lower()

        # Biomarker definitions with search terms and default units
        biomarker_defs = {
            "creatinine": {"terms": ["creatinine", "cr", "scr"], "default_unit": "mg/dL", "alt_units": ["µmol/L"]},
            "egfr": {"terms": ["egfr", "gfr"], "default_unit": "mL/min/1.73m²", "alt_units": []},
            "hba1c": {"terms": ["hba1c", "a1c", "hemoglobin a1c"], "default_unit": "%", "alt_units": ["mmol/mol"]},
            "glucose": {"terms": ["glucose", "blood sugar", "fbs", "fasting glucose"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "potassium": {"terms": ["potassium", "k+", "k"], "default_unit": "mEq/L", "alt_units": ["mmol/L"]},
            "sodium": {"terms": ["sodium", "na+", "na"], "default_unit": "mEq/L", "alt_units": ["mmol/L"]},
            "albumin": {"terms": ["albumin", "serum albumin"], "default_unit": "g/dL", "alt_units": ["g/L"]},
            "hemoglobin": {"terms": ["hemoglobin", "hb", "hgb"], "default_unit": "g/dL", "alt_units": ["g/L"]},
            "ferritin": {"terms": ["ferritin"], "default_unit": "ng/mL", "alt_units": ["µg/L"]},
            "urea": {"terms": ["urea", "bun", "blood urea nitrogen"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "calcium": {"terms": ["calcium", "ca"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "phosphorus": {"terms": ["phosphorus", "phosphate"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "magnesium": {"terms": ["magnesium", "mg"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "alt": {"terms": ["alt", "alanine transaminase", "sgpt"], "default_unit": "U/L", "alt_units": []},
            "tsh": {"terms": ["tsh", "thyroid stimulating hormone"], "default_unit": "mIU/L", "alt_units": []},
            "triglycerides": {"terms": ["triglycerides", "tg"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "ldl": {"terms": ["ldl", "ldl cholesterol", "low density lipoprotein"], "default_unit": "mg/dL", "alt_units": ["mmol/L"]},
            "ammonia": {"terms": ["ammonia", "nh3"], "default_unit": "µmol/L", "alt_units": ["µg/dL"]},
            "leucine": {"terms": ["leucine"], "default_unit": "µmol/L", "alt_units": ["mg/dL"]},
            "phenylalanine": {"terms": ["phenylalanine", "phe"], "default_unit": "mg/dL", "alt_units": ["µmol/L"]},
        }

        # Check for negation patterns first
        negation_patterns = [
            r'\b(no|not|without|never|don\'t have|do not have)\s+\w*\s*(elevated|high|abnormal|lab|test|result)',
            r'\b(normal|within normal)\s+(range|limits)'
        ]
        has_negation = any(re.search(pattern, query_lower) for pattern in negation_patterns)

        if has_negation:
            logger.info("Negation detected in query - biomarkers may be mentioned but not present")

        # Extract biomarkers with values
        for biomarker, config in biomarker_defs.items():
            for term in config["terms"]:
                # Build regex pattern: term followed by optional value and unit
                # Handles: "creatinine 2.1 mg/dL", "HbA1c: 8.5%", "glucose = 120 mg/dL"
                pattern = rf'\b{re.escape(term)}\s*[:\-=]?\s*(\d+\.?\d*)\s*(%|mg/dL|g/dL|mEq/L|mmol/L|µmol/L|ng/mL|U/L|mIU/L|µg/dL|µg/L|g/L|mL/min/1\.73m²)?'

                match = re.search(pattern, query_lower, re.IGNORECASE)
                if match:
                    value = float(match.group(1))
                    unit = match.group(2) if match.group(2) else config["default_unit"]

                    # CRITICAL FIX: Validate biomarker value
                    validation = self._validate_biomarker_value(biomarker, value, unit)

                    # Only store if value is valid (not impossible)
                    if validation["valid"]:
                        biomarkers[biomarker] = {
                            "value": value,
                            "unit": unit,
                            "raw": match.group(0),
                            "term_used": term,
                            "validation": validation  # Include validation info
                        }

                        # Log warnings for critical values
                        if validation["severity"] == "critical":
                            logger.warning(f"Critical biomarker value detected: {validation['warning']}")
                    else:
                        # Log rejection of impossible values
                        logger.warning(f"Rejected impossible biomarker value: {validation['warning']}")

                    break  # Found this biomarker, move to next

        return biomarkers
    
    def detect_high_risk(self, query: str) -> bool:
        """Detect high-risk clinical scenarios with safety checks"""
        high_risk_terms = [
            "pregnant", "pregnancy", "breastfeeding", "lactating",
            "ckd", "kidney disease", "dialysis", "hemodialysis",
            "diabetes", "cancer", "tumor", "chemotherapy",
            "heart failure", "cirrhosis", "malnutrition",
            "anemia", "osteoporosis", "allergy", "intolerance",
            "PKU", "phenylketonuria", "inborn error",
            "MSUD", "methylmalonic", "urea cycle", "homocystinuria",
            "renal failure", "chronic kidney disease", "diabetic ketoacidosis",
            "hypoglycemia", "hyperkalemia", "hypernatremia", "hypocalcemia"
        ]
        
        query_lower = query.lower()
        is_high_risk = any(term in query_lower for term in high_risk_terms)
        
        # Additional safety checks for high-risk scenarios
        if is_high_risk:
            # Check for critical lab values
            if "k+" in query_lower or "potassium" in query_lower and any(num in query_lower for num in ["6.5", "7.0", "7.5"]):
                return True
            if "k+" in query_lower or "potassium" in query_lower and any(num in query_lower for num in ["2.5", "2.0", "1.5"]):
                return True
            if "sodium" in query_lower and any(num in query_lower for num in ["155", "160", "165"]):
                return True
            if "sodium" in query_lower and any(num in query_lower for num in ["120", "115", "110"]):
                return True
        
        return is_high_risk
    
    def _extract_diagnosis(self, query: str) -> Optional[str]:
        """
        Extract diagnosis from query patterns like:
        - "Diet therapy for Type 1 Diabetes"
        - "Therapy plan for CKD"
        - "My child has epilepsy"
        - "PKU diet plan"
        """
        query_lower = query.lower()

        # Pattern 1: "for [diagnosis]" patterns
        # Matches: "therapy for type 1 diabetes", "diet for ckd", "plan for epilepsy"
        for_pattern = r'\b(?:for|with)\s+([a-z0-9\s\-]+?)(?:\s+(?:diet|therapy|plan|nutrition|meal|treatment)|$)'
        match = re.search(for_pattern, query_lower)
        if match:
            diagnosis = match.group(1).strip()
            # Filter out non-diagnosis terms
            if diagnosis and len(diagnosis) > 2 and diagnosis not in ['a', 'an', 'the', 'my', 'this', 'that']:
                return diagnosis.title()

        # Pattern 2: "has [diagnosis]" patterns
        # Matches: "my child has type 1 diabetes", "patient has ckd"
        has_pattern = r'\b(?:has|have|diagnosed with|suffering from)\s+([a-z0-9\s\-]+?)(?:\s+(?:and|,|\.)|$)'
        match = re.search(has_pattern, query_lower)
        if match:
            diagnosis = match.group(1).strip()
            if diagnosis and len(diagnosis) > 2:
                return diagnosis.title()

        # Pattern 3: Direct diagnosis mentions (exact match with known conditions)
        diagnosis_keywords = {
            "type 1 diabetes": "Type 1 Diabetes",
            "t1d": "Type 1 Diabetes",
            "diabetes type 1": "Type 1 Diabetes",
            "pku": "PKU",
            "phenylketonuria": "Phenylketonuria",
            "msud": "MSUD",
            "maple syrup urine disease": "MSUD",
            "galactosemia": "Galactosemia",
            "ckd": "Chronic Kidney Disease",
            "chronic kidney disease": "Chronic Kidney Disease",
            "renal disease": "Chronic Kidney Disease",
            "epilepsy": "Epilepsy",
            "seizure": "Epilepsy",
            "cystic fibrosis": "Cystic Fibrosis",
            "cf": "Cystic Fibrosis",
            "preterm": "Preterm Nutrition",
            "premature": "Preterm Nutrition",
            "nicu": "Preterm Nutrition",
            "food allergy": "Food Allergy",
            "food allergies": "Food Allergy",
            "ibd": "IBD",
            "crohn": "Crohn's Disease",
            "crohn's": "Crohn's Disease",
            "ulcerative colitis": "Ulcerative Colitis",
            "gerd": "GERD",
            "reflux": "GERD"
        }

        for keyword, diagnosis in diagnosis_keywords.items():
            if keyword in query_lower:
                return diagnosis

        return None

    def _extract_country(self, query: str) -> Optional[str]:
        """Extract country from query for FCT data mapping"""
        country_terms = {
            "nigeria": "Nigeria",
            "kenya": "Kenya",
            "canada": "Canada",
            "ghana": "Ghana",
            "uganda": "Uganda",
            "tanzania": "Tanzania",
            "south africa": "South Africa",
            "zimbabwe": "Zimbabwe",
            "congo": "Congo",
            "mozambique": "Mozambique",
            "lesotho": "Lesotho",
            "malawi": "Malawi",
            "india": "India",
            "korea": "Korea",
            "west africa": "West Africa"
        }
        
        query_lower = query.lower()
        for term, country in country_terms.items():
            if term in query_lower:
                return country
        
        # Check for demonyms
        demonyms = {
            "nigerian": "Nigeria",
            "kenyan": "Kenya",
            "canadian": "Canada",
            "ghanaian": "Ghana",
            "ugandan": "Uganda",
            "tanzanian": "Tanzania",
            "south african": "South Africa",
            "zimbabwean": "Zimbabwe",
            "congo": "Congo",
            "mozambican": "Mozambique",
            "lesotho": "Lesotho",
            "malawian": "Malawi",
            "indian": "India",
            "korean": "Korea"
        }
        
        for term, country in demonyms.items():
            if term in query_lower:
                return country
        
        return None
    
    def is_rejection(self, response: str) -> bool:
        """
        Detect if user is rejecting/declining to provide information.

        Returns True for: "no", "don't have", "not available", "none", "refuse", etc.
        """
        rejection_phrases = [
            r'\b(no|nope|nah)\b',
            r'\b(don\'t have|do not have|dont have)\b',
            r'\b(not available|unavailable)\b',
            r'\b(don\'t know|do not know|dont know)\b',
            r'\bnone\b',
            r'\b(refuse|won\'t|will not|cannot|can\'t)\b',
            r'\b(skip|pass|next)\b',
            r'\b(not sure|unsure|uncertain)\b',
        ]

        response_lower = response.lower().strip()

        # Check for exact matches first (common short responses)
        if response_lower in ['no', 'nope', 'nah', 'none', 'n/a', 'na', 'skip', 'pass']:
            return True

        # Check regex patterns
        return any(re.search(pattern, response_lower) for pattern in rejection_phrases)

    def extract_from_followup_response(self, response: str, awaiting_slot: str) -> dict:
        """
        Extract value when we know what slot we're awaiting.

        Args:
            response: User's response to follow-up question
            awaiting_slot: The slot we asked for (e.g., "creatinine", "medications", "age")

        Returns:
            {
                "found": True/False,
                "value": extracted value (if found),
                "unit": unit (for biomarkers),
                "reason": explanation if not found ("user_rejected", "unclear_response", "out_of_range")
            }
        """
        # Check rejection first
        if self.is_rejection(response):
            return {"found": False, "reason": "user_rejected", "raw_response": response}

        # Handle biomarker slots - expect numeric values
        if awaiting_slot in BIOMARKERS:
            # Try to extract number + optional unit
            match = re.search(r'(\d+\.?\d*)\s*(%|mg/dL|g/dL|mEq/L|mmol/L|µmol/L|ng/mL|U/L|mIU/L|µg/dL|µg/L|g/L|mL/min/1\.73m²)?', response)

            if match:
                value = float(match.group(1))
                unit = match.group(2) if match.group(2) else self._get_default_unit(awaiting_slot)

                # Validate range (basic sanity check)
                if self._validate_biomarker_range(awaiting_slot, value, unit):
                    return {
                        "found": True,
                        "value": value,
                        "unit": unit,
                        "biomarker": awaiting_slot
                    }
                else:
                    return {
                        "found": False,
                        "reason": "out_of_range",
                        "value": value,
                        "unit": unit,
                        "message": f"{awaiting_slot} value {value} {unit} seems unusual. Please confirm."
                    }
            else:
                return {"found": False, "reason": "unclear_response", "raw_response": response}

        # Handle medication slots - expect drug names
        elif awaiting_slot == "medications":
            # Extract medication names from response
            meds = self.extract_medications(response)
            if meds:
                return {"found": True, "medications": meds}
            else:
                return {"found": False, "reason": "no_medications_found", "raw_response": response}

        # Handle other slots (age, weight, allergies)
        else:
            return {"found": True, "value": response, "slot": awaiting_slot}

    def _get_default_unit(self, biomarker: str) -> str:
        """Get default unit for a biomarker"""
        unit_map = {
            "creatinine": "mg/dL",
            "hba1c": "%",
            "glucose": "mg/dL",
            "potassium": "mEq/L",
            "sodium": "mEq/L",
            "albumin": "g/dL",
            "hemoglobin": "g/dL",
            "ferritin": "ng/mL",
            "egfr": "mL/min/1.73m²",
        }
        return unit_map.get(biomarker, "")

    def _validate_biomarker_range(self, biomarker: str, value: float, unit: str) -> bool:
        """Basic range validation to catch obvious errors"""
        # Define reasonable ranges (not clinical reference ranges)
        ranges = {
            "creatinine": (0.1, 20.0),  # mg/dL - catches typos
            "hba1c": (3.0, 20.0),  # % - catches unrealistic values
            "glucose": (20.0, 800.0),  # mg/dL
            "potassium": (1.5, 10.0),  # mEq/L
            "sodium": (100.0, 180.0),  # mEq/L
            "albumin": (1.0, 6.0),  # g/dL
            "hemoglobin": (3.0, 25.0),  # g/dL
            "egfr": (1.0, 150.0),  # mL/min
        }

        if biomarker in ranges:
            min_val, max_val = ranges[biomarker]
            return min_val <= value <= max_val

        return True  # Unknown biomarker - assume valid

    def _needs_followup(self, label: str, query: str) -> bool:
        if label in ["therapy", "recommendation"]:
            return True
        if label == "comparison":
            return not any(x in query.lower() for x in ["raw", "boiled", "soaked", "dry", "fermented"])
        return False
        
    def estimate_complexity(self, query: str, label: str) -> int:
        """Estimate query complexity on a 1-5 scale with safety checks"""
        # Base complexity on query type
        complexity = 3  # Default
        if label == "comparison":
            complexity = 2
        elif label == "general":
            complexity = 2
        elif label in ["recommendation", "therapy"]:
            complexity = 4
        
        # Increase complexity for longer queries or specific terms
        if len(query.split()) > 15:
            complexity = min(5, complexity + 1)
        
        # Increase for high-risk scenarios
        if self.detect_high_risk(query):
            complexity = min(5, complexity + 1)
        
        # Additional safety checks for complexity
        if "emergency" in query.lower() or "urgent" in query.lower():
            complexity = 5

        return complexity

    # ============================================================================
    # NEW METHODS FOR THERAPY FLOW
    # ============================================================================

    def normalize_diagnosis(self, diagnosis: Optional[str]) -> Optional[str]:
        """
        Normalize diagnosis to match supported therapy conditions.

        Maps user input/extracted diagnosis to canonical names from SUPPORTED_THERAPY_CONDITIONS.

        Args:
            diagnosis: Extracted or user-provided diagnosis

        Returns:
            Normalized diagnosis if in supported list, otherwise original diagnosis
        """
        if not diagnosis:
            return None

        diagnosis_lower = diagnosis.lower().strip()

        # Direct match with supported therapy conditions
        if diagnosis_lower in SUPPORTED_THERAPY_CONDITIONS:
            return SUPPORTED_THERAPY_CONDITIONS[diagnosis_lower]

        # Partial match (for longer diagnoses containing keywords)
        for key, canonical in SUPPORTED_THERAPY_CONDITIONS.items():
            if key in diagnosis_lower or diagnosis_lower in key:
                return canonical

        # Return original if no match (might be valid but not in therapy list)
        return diagnosis

    def is_diagnosis_supported_for_therapy(self, diagnosis: Optional[str]) -> bool:
        """
        Check if diagnosis is in the supported therapy list.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if diagnosis is supported for therapy flow, False otherwise
        """
        if not diagnosis:
            return False

        normalized = self.normalize_diagnosis(diagnosis)
        return normalized in SUPPORTED_THERAPY_CONDITIONS.values()

    def extract_medications_with_dosage(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract medications with dosage information.

        Patterns:
        - "insulin 20 units"
        - "metformin 500mg"
        - "phenytoin 100 mg twice daily"

        Args:
            query: User query

        Returns:
            List of dicts with keys: name, dose, frequency
        """
        medications_with_dosage = []
        query_lower = query.lower()

        # Pattern for medication + dosage
        # Matches: "insulin 20 units", "metformin 500mg", "phenytoin 100 mg"
        dosage_pattern = r'(\w+)\s+(\d+\.?\d*)\s*(mg|g|units?|ml|mcg|μg|iu)(?:\s+(daily|twice daily|tds|bd|qd|bid|tid))?'

        matches = re.finditer(dosage_pattern, query_lower)

        for match in matches:
            med_name = match.group(1)
            dose_value = match.group(2)
            dose_unit = match.group(3)
            frequency = match.group(4) if match.group(4) else None

            # Check if this is a known medication
            if med_name in [m.lower() for m in MEDICATIONS]:
                medications_with_dosage.append({
                    "name": med_name.capitalize(),
                    "dose": f"{dose_value} {dose_unit}",
                    "frequency": frequency
                })

        # If no dosages found, fallback to simple medication extraction
        if not medications_with_dosage:
            simple_meds = self.extract_medications(query)
            for med in simple_meds:
                medications_with_dosage.append({
                    "name": med,
                    "dose": None,
                    "frequency": None
                })

        return medications_with_dosage

    def extract_entities_enhanced(self, query: str) -> Dict[str, Any]:
        """
        Enhanced entity extraction with normalization and validation.

        This method combines all extraction logic with:
        - Diagnosis normalization
        - Medication dosage extraction
        - Biomarker validation (already implemented)
        - Age/weight/height extraction

        Args:
            query: User query

        Returns:
            Dict with all extracted entities including normalized diagnosis
        """
        entities = {}

        # Extract and normalize diagnosis
        raw_diagnosis = self._extract_diagnosis(query)
        if raw_diagnosis:
            entities["diagnosis"] = raw_diagnosis
            entities["diagnosis_normalized"] = self.normalize_diagnosis(raw_diagnosis)
            entities["diagnosis_supported"] = self.is_diagnosis_supported_for_therapy(raw_diagnosis)

        # Extract medications with dosage
        meds_with_dosage = self.extract_medications_with_dosage(query)
        if meds_with_dosage:
            entities["medications"] = [m["name"] for m in meds_with_dosage]
            entities["medications_detailed"] = meds_with_dosage

        # Extract biomarkers (already has validation)
        biomarkers_detailed = self.extract_biomarkers_with_values(query)
        if biomarkers_detailed:
            entities["biomarkers"] = list(biomarkers_detailed.keys())
            entities["biomarkers_detailed"] = biomarkers_detailed

        # Extract age, weight, height (already implemented in extract_from_followup_response)
        age_match = re.search(r'\b(\d+)\s*(?:years?|yrs?|y\.o\.|year old)\b', query.lower())
        if age_match:
            entities["age"] = int(age_match.group(1))

        weight_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:kg|kilograms?)\b', query.lower())
        if weight_match:
            entities["weight_kg"] = float(weight_match.group(1))

        height_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b', query.lower())
        if height_match:
            entities["height_cm"] = float(height_match.group(1))

        # Extract country
        country = self._extract_country(query)
        if country:
            entities["country"] = country

        return entities