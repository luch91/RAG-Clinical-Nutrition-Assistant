import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import os
import re
from app.config.config import DISTILBERT_CLASSIFIER_PATH
import logging
from typing import Optional
from app.common.custom_exception import CustomException

logger = logging.getLogger(__name__)

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
            
            # Rule-based enhancements
            result = {
                "label": label,
                "biomarkers": self.extract_biomarkers(query),
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
                "biomarkers": [],
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
        """Detect clinical biomarkers in the query with validation"""
        biomarkers = []
        query_lower = query.lower()
        
        # Comprehensive biomarker detection
        biomarker_map = {
            "creatinine": "creatinine",
            "egfr": "egfr",
            "urea": "urea",
            "hba1c": "hba1c",
            "glucose": "glucose",
            "ldl": "ldl_cholesterol",
            "triglycerides": "triglycerides",
            "potassium": "potassium",
            "sodium": "sodium",
            "magnesium": "magnesium",
            "calcium": "calcium",
            "zinc": "zinc",
            "vitamin_d": "vitamin_d",
            "vitamin_b12": "vitamin_b12",
            "vitamin_a": "vitamin_a",
            "vitamin_k": "vitamin_k",
            "vitamin_e": "vitamin_e",
            "folate": "folate",
            "hemoglobin": "hemoglobin",
            "ferritin": "ferritin",
            "transferrin": "transferrin_saturation",
            "albumin": "albumin",
            "alt": "alt",
            "tsh": "tsh",
            "ammonia": "ammonia",
            "leucine": "leucine",
            "phenylalanine": "phenylalanine"
        }
        
        for term, biomarker in biomarker_map.items():
            if term in query_lower:
                biomarkers.append(biomarker)
        
        # Validate biomarkers - ensure they're clinically relevant
        valid_biomarkers = [b for b in biomarkers if b in biomarker_map.values()]
        if len(valid_biomarkers) != len(biomarkers):
            logger.warning(f"Invalid biomarkers detected: {set(biomarkers) - set(valid_biomarkers)}")
        
        return valid_biomarkers
    
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