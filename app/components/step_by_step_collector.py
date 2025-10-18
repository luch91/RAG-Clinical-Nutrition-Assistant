"""
Dedicated Step-by-Step Therapy Data Collector

Clean, linear state machine for therapy data collection.
Eliminates fragmented logic and provides predictable UX.
"""
from typing import Dict, Any, Optional, List
from app.common.logger import get_logger

logger = get_logger(__name__)


class StepByStepTherapyCollector:
    """
    Linear flow for collecting therapy data one question at a time.

    Usage:
        collector = StepByStepTherapyCollector(diagnosis="Type 1 Diabetes")
        response = collector.start()  # First question

        # User answers
        response = collector.process_answer("12")  # age
        response = collector.process_answer("45")  # weight
        # ... until complete

        # When done:
        if collector.is_complete():
            data = collector.get_collected_data()
    """

    def __init__(self, diagnosis: Optional[str] = None, initial_slots: Optional[Dict[str, Any]] = None):
        """
        Initialize collector.

        Args:
            diagnosis: Pre-extracted diagnosis from initial query (optional)
            initial_slots: Any slots already extracted (age, weight, etc.)
        """
        self.diagnosis = diagnosis
        self.initial_slots = initial_slots or {}
        self.collected_data = {"diagnosis": diagnosis} if diagnosis else {}

        # Define collection steps
        self.steps = self._define_steps()
        self.current_step_index = 0

        # Skip steps that are already filled from initial query
        self._skip_prefilled_steps()

        logger.info(f"StepByStepTherapyCollector initialized: diagnosis={diagnosis}, steps={len(self.steps)}")

    def _define_steps(self) -> List[Dict[str, Any]]:
        """Define the steps in order"""
        steps = []

        # Only ask for diagnosis if not provided
        if not self.diagnosis:
            steps.append({
                "slot": "diagnosis",
                "question": "What is the patient's diagnosis or medical condition?",
                "hint": "e.g., Type 1 Diabetes, CKD, Epilepsy",
                "required": True,
                "parser": "string"
            })

        # Age (always required)
        if "age" not in self.initial_slots:
            steps.append({
                "slot": "age",
                "question": "What is the patient's age in years?",
                "hint": "Enter age (0-18 for pediatric)",
                "required": True,
                "parser": "number"
            })

        # Weight
        if "weight_kg" not in self.initial_slots:
            steps.append({
                "slot": "weight_kg",
                "question": "What is the patient's weight in kilograms?",
                "hint": "Enter weight in kg",
                "required": True,
                "parser": "number"
            })

        # Height
        if "height_cm" not in self.initial_slots:
            steps.append({
                "slot": "height_cm",
                "question": "What is the patient's height in centimeters?",
                "hint": "Enter height in cm",
                "required": True,
                "parser": "number"
            })

        # Medications
        if "medications" not in self.initial_slots:
            steps.append({
                "slot": "medications",
                "question": "What medications is the patient currently taking?",
                "hint": "List medications separated by commas, or type 'none'",
                "required": True,
                "parser": "medication_list"
            })

        # Biomarkers (diagnosis-specific)
        biomarker_questions = self._get_biomarker_questions()
        steps.extend(biomarker_questions)

        # Allergies
        if "allergies" not in self.initial_slots:
            steps.append({
                "slot": "allergies",
                "question": "Does the patient have any food allergies?",
                "hint": "List allergies separated by commas, or type 'none'",
                "required": False,
                "parser": "allergy_list"
            })

        # Country (optional but helpful)
        if "country" not in self.initial_slots:
            steps.append({
                "slot": "country",
                "question": "Which country are you in? (for food availability)",
                "hint": "e.g., Nigeria, Kenya, Canada, USA",
                "required": False,
                "parser": "string"
            })

        return steps

    def _get_biomarker_questions(self) -> List[Dict[str, Any]]:
        """Get diagnosis-specific biomarker questions for ALL 8 supported conditions"""
        questions = []

        diagnosis_lower = (self.diagnosis or "").lower()

        # 1. Type 1 Diabetes
        if "diabet" in diagnosis_lower or "t1d" in diagnosis_lower or "iddm" in diagnosis_lower:
            questions.append({
                "slot": "hba1c",
                "question": "What is the patient's HbA1c level?",
                "hint": "Enter HbA1c value (e.g., 7.5) or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "%"
            })
            questions.append({
                "slot": "glucose",
                "question": "What is the patient's fasting glucose level?",
                "hint": "Enter glucose in mg/dL (e.g., 120) or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mg/dL"
            })

        # 2. Chronic Kidney Disease (CKD)
        elif "ckd" in diagnosis_lower or "kidney" in diagnosis_lower or "renal" in diagnosis_lower:
            questions.append({
                "slot": "creatinine",
                "question": "What is the patient's serum creatinine level?",
                "hint": "Enter creatinine in mg/dL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mg/dL"
            })
            questions.append({
                "slot": "egfr",
                "question": "What is the patient's eGFR?",
                "hint": "Enter eGFR in mL/min/1.73m² or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mL/min/1.73m²"
            })
            questions.append({
                "slot": "potassium",
                "question": "What is the patient's potassium level?",
                "hint": "Enter K+ in mEq/L or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mEq/L"
            })
            questions.append({
                "slot": "phosphorus",
                "question": "What is the patient's phosphorus level?",
                "hint": "Enter phosphorus in mg/dL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mg/dL"
            })

        # 3. Inherited Metabolic Disorders (PKU, MSUD, Galactosemia) - CHECK BEFORE EPILEPSY
        # IMPORTANT: Must be before epilepsy check because "keto" in epilepsy matches "phenylKETOnuria"
        elif any(term in diagnosis_lower for term in ["pku", "phenylketonuria", "msud", "maple syrup", "galactosemia", "metabolic disorder", "inborn error"]):
            # PKU-specific
            if "pku" in diagnosis_lower or "phenylketonuria" in diagnosis_lower:
                questions.append({
                    "slot": "phenylalanine",
                    "question": "What is the patient's blood phenylalanine level?",
                    "hint": "Enter phenylalanine in mg/dL or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "mg/dL"
                })
                questions.append({
                    "slot": "tyrosine",
                    "question": "What is the patient's blood tyrosine level?",
                    "hint": "Enter tyrosine in mg/dL or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "mg/dL"
                })

            # MSUD-specific
            elif "msud" in diagnosis_lower or "maple syrup" in diagnosis_lower:
                questions.append({
                    "slot": "leucine",
                    "question": "What is the patient's blood leucine level?",
                    "hint": "Enter leucine in µmol/L or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "µmol/L"
                })
                questions.append({
                    "slot": "isoleucine",
                    "question": "What is the patient's blood isoleucine level?",
                    "hint": "Enter isoleucine in µmol/L or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "µmol/L"
                })
                questions.append({
                    "slot": "valine",
                    "question": "What is the patient's blood valine level?",
                    "hint": "Enter valine in µmol/L or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "µmol/L"
                })

            # Galactosemia-specific
            elif "galactosemia" in diagnosis_lower:
                questions.append({
                    "slot": "galactose_1_phosphate",
                    "question": "What is the patient's galactose-1-phosphate level?",
                    "hint": "Enter galactose-1-phosphate in mg/dL or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "mg/dL"
                })
                questions.append({
                    "slot": "galt_activity",
                    "question": "What is the patient's GALT enzyme activity?",
                    "hint": "Enter GALT activity percentage or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "%"
                })

            # General metabolic markers (for all IEMs)
            questions.append({
                "slot": "albumin",
                "question": "What is the patient's albumin level?",
                "hint": "Enter albumin in g/dL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "g/dL"
            })

        # 4. Epilepsy / Ketogenic Therapy - AFTER metabolic disorders
        elif "epilep" in diagnosis_lower or "seizure" in diagnosis_lower or "ketogenic" in diagnosis_lower or "keto" in diagnosis_lower:
            questions.append({
                "slot": "aed_level",
                "question": "What are the patient's anti-epileptic drug levels (if known)?",
                "hint": "Enter drug levels or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": ""
            })
            questions.append({
                "slot": "ketone_level",
                "question": "What is the patient's blood ketone level (if on ketogenic diet)?",
                "hint": "Enter ketone level in mmol/L or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "mmol/L"
            })
            questions.append({
                "slot": "seizure_frequency",
                "question": "How many seizures per month does the patient experience?",
                "hint": "Enter average number per month or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "per month"
            })

        # 5. Cystic Fibrosis (CF)
        elif "cystic fibrosis" in diagnosis_lower or "cf" in diagnosis_lower or "cftr" in diagnosis_lower:
            questions.append({
                "slot": "fev1",
                "question": "What is the patient's FEV1 (lung function)?",
                "hint": "Enter FEV1 percentage (e.g., 75) or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "%"
            })
            questions.append({
                "slot": "pancreatic_status",
                "question": "Is the patient pancreatic insufficient? (yes/no/unknown)",
                "hint": "Type 'yes', 'no', or 'unknown'",
                "required": False,
                "parser": "string",
                "unit": ""
            })
            questions.append({
                "slot": "vitamin_d",
                "question": "What is the patient's vitamin D level?",
                "hint": "Enter vitamin D in ng/mL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "ng/mL"
            })
            questions.append({
                "slot": "vitamin_a",
                "question": "What is the patient's vitamin A level?",
                "hint": "Enter vitamin A in µg/dL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "µg/dL"
            })

        # 6. Preterm Nutrition
        elif "preterm" in diagnosis_lower or "premature" in diagnosis_lower or "nicu" in diagnosis_lower or "preemie" in diagnosis_lower:
            questions.append({
                "slot": "gestational_age",
                "question": "What was the baby's gestational age at birth?",
                "hint": "Enter weeks (e.g., 32) or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "weeks"
            })
            questions.append({
                "slot": "corrected_age",
                "question": "What is the baby's corrected age?",
                "hint": "Enter corrected age in weeks or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "weeks"
            })
            questions.append({
                "slot": "feeding_method",
                "question": "What is the current feeding method?",
                "hint": "e.g., breast milk, formula, mixed, or 'unknown'",
                "required": False,
                "parser": "string",
                "unit": ""
            })
            questions.append({
                "slot": "hemoglobin",
                "question": "What is the baby's hemoglobin level?",
                "hint": "Enter hemoglobin in g/dL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "g/dL"
            })

        # 7. Food Allergy
        elif "food allerg" in diagnosis_lower or "allergic" in diagnosis_lower or "anaphylaxis" in diagnosis_lower:
            questions.append({
                "slot": "allergen_type",
                "question": "What foods is the patient allergic to?",
                "hint": "List specific allergens (e.g., peanuts, milk, eggs)",
                "required": False,
                "parser": "string",
                "unit": ""
            })
            questions.append({
                "slot": "ige_level",
                "question": "What is the patient's total IgE level (if known)?",
                "hint": "Enter IgE in IU/mL or 'unknown'",
                "required": False,
                "parser": "biomarker",
                "unit": "IU/mL"
            })
            questions.append({
                "slot": "reaction_severity",
                "question": "What is the severity of reactions? (mild/moderate/severe)",
                "hint": "Type 'mild', 'moderate', 'severe', or 'unknown'",
                "required": False,
                "parser": "string",
                "unit": ""
            })

        # 8. GI Disorders (IBD, GERD, Crohn's, Ulcerative Colitis)
        elif any(term in diagnosis_lower for term in ["ibd", "crohn", "ulcerative colitis", "gerd", "reflux", "inflammatory bowel"]):
            # IBD-specific (Crohn's, UC)
            if any(term in diagnosis_lower for term in ["ibd", "crohn", "ulcerative colitis", "inflammatory bowel"]):
                questions.append({
                    "slot": "crp",
                    "question": "What is the patient's C-reactive protein (CRP) level?",
                    "hint": "Enter CRP in mg/L or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "mg/L"
                })
                questions.append({
                    "slot": "esr",
                    "question": "What is the patient's ESR (sedimentation rate)?",
                    "hint": "Enter ESR in mm/hr or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "mm/hr"
                })
                questions.append({
                    "slot": "fecal_calprotectin",
                    "question": "What is the patient's fecal calprotectin level?",
                    "hint": "Enter calprotectin in µg/g or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "µg/g"
                })
                questions.append({
                    "slot": "albumin",
                    "question": "What is the patient's albumin level?",
                    "hint": "Enter albumin in g/dL or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "g/dL"
                })

            # GERD-specific
            if "gerd" in diagnosis_lower or "reflux" in diagnosis_lower:
                questions.append({
                    "slot": "symptom_frequency",
                    "question": "How many times per week does the patient experience reflux symptoms?",
                    "hint": "Enter frequency per week or 'unknown'",
                    "required": False,
                    "parser": "biomarker",
                    "unit": "per week"
                })

        return questions

    def _skip_prefilled_steps(self):
        """Skip steps that are already filled from initial query"""
        while self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            slot = step["slot"]

            if slot in self.initial_slots:
                self.collected_data[slot] = self.initial_slots[slot]
                logger.info(f"Skipping {slot} (already provided): {self.initial_slots[slot]}")
                self.current_step_index += 1
            else:
                break

    def start(self) -> Dict[str, Any]:
        """Get the first question"""
        return self.next_question()

    def next_question(self) -> Dict[str, Any]:
        """Get the next question in sequence"""
        if self.is_complete():
            return self._completion_response()

        step = self.steps[self.current_step_index]
        progress = f"({self.current_step_index + 1}/{len(self.steps)})"

        question_text = f"{step['question']} {progress}\n\n💡 {step['hint']}"

        return {
            "template": "followup",
            "answer": question_text,
            "followups": [],
            "model_used": "none",
            "therapy_output": None,
            "therapy_summary": None,
            "sources_used": [],
            "citations": [],
            "model_note": f"Step-by-step collection: {step['slot']}",
            "warnings": [],
            "composer_placeholder": step['hint'],
            "awaiting_slot": step['slot'],
            "step_by_step_mode": True
        }

    def process_answer(self, answer: str) -> Dict[str, Any]:
        """
        Process user's answer to current question.

        Returns response dict with either:
        - Next question (if more steps remain)
        - Completion message (if all done)
        - Retry message (if answer invalid)
        """
        if self.is_complete():
            return self._completion_response()

        step = self.steps[self.current_step_index]
        slot = step["slot"]
        parser = step["parser"]

        # Parse answer based on type
        result = self._parse_answer(answer, parser, slot)

        if result["valid"]:
            # Save and move to next
            self.collected_data[slot] = result["value"]
            logger.info(f"✅ Collected {slot}: {result['value']}")

            self.current_step_index += 1
            return self.next_question()
        else:
            # Invalid - ask again
            return {
                "template": "followup",
                "answer": f"⚠️ {result['error']}\n\n{step['question']}\n\n💡 {step['hint']}",
                "followups": [],
                "model_used": "none",
                "therapy_output": None,
                "therapy_summary": None,
                "sources_used": [],
                "citations": [],
                "model_note": f"Retry: {slot}",
                "warnings": ["parsing_error"],
                "composer_placeholder": step['hint'],
                "awaiting_slot": slot,
                "step_by_step_mode": True
            }

    def _parse_answer(self, answer: str, parser: str, slot: str) -> Dict[str, Any]:
        """Parse answer based on parser type"""
        answer_clean = answer.strip()
        answer_lower = answer_clean.lower()

        # Handle "unknown" / "skip" for optional fields
        if answer_lower in ["unknown", "skip", "n/a", "na", "none", "no"]:
            if parser in ["biomarker", "allergy_list"]:
                return {"valid": True, "value": None}

        # String parser
        if parser == "string":
            if len(answer_clean) < 2:
                return {"valid": False, "error": "Please provide a valid answer (at least 2 characters)."}
            return {"valid": True, "value": answer_clean}

        # Number parser
        elif parser == "number":
            try:
                value = float(answer_clean)
                if value <= 0:
                    return {"valid": False, "error": "Please enter a positive number."}
                return {"valid": True, "value": value}
            except ValueError:
                return {"valid": False, "error": f"Please enter a valid number for {slot}."}

        # Medication list parser
        elif parser == "medication_list":
            # Preprocessing: remove common filler words
            cleaned = answer_clean
            for filler in ["yes.", "yes,", "yeah.", "yeah,", "yep.", "yep,"]:
                cleaned = cleaned.replace(filler, "").strip()

            if answer_lower in ["none", "no", "nil", "n/a"]:
                return {"valid": True, "value": []}

            # Split by comma
            medications = [m.strip() for m in cleaned.split(",") if m.strip()]

            if not medications:
                return {"valid": False, "error": "Please list medications separated by commas, or type 'none'."}

            return {"valid": True, "value": medications}

        # Allergy list parser
        elif parser == "allergy_list":
            if answer_lower in ["none", "no", "nil", "n/a", "nka", "nkda"]:
                return {"valid": True, "value": ["none"]}

            allergies = [a.strip() for a in answer_clean.split(",") if a.strip()]
            return {"valid": True, "value": allergies}

        # Biomarker parser
        elif parser == "biomarker":
            if answer_lower in ["unknown", "skip", "n/a"]:
                return {"valid": True, "value": None}

            try:
                value = float(answer_clean)
                return {"valid": True, "value": value}
            except ValueError:
                return {"valid": False, "error": f"Please enter a numeric value or 'unknown'."}

        # Fallback
        return {"valid": False, "error": "Invalid input."}

    def is_complete(self) -> bool:
        """Check if all steps are complete"""
        return self.current_step_index >= len(self.steps)

    def get_collected_data(self) -> Dict[str, Any]:
        """Get all collected data"""
        return self.collected_data.copy()

    def _completion_response(self) -> Dict[str, Any]:
        """Return completion message"""
        return {
            "template": "followup",
            "answer": "✅ **All information collected!** Generating your personalized therapy plan...\n\n⏳ This may take 30-60 seconds.",
            "followups": [],
            "model_used": "none",
            "therapy_output": None,
            "therapy_summary": None,
            "sources_used": [],
            "citations": [],
            "model_note": "Step-by-step collection complete - ready for therapy generation",
            "warnings": [],
            "composer_placeholder": "",
            "step_by_step_complete": True,
            "collected_data": self.get_collected_data()
        }
