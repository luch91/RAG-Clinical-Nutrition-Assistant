# app/components/intent_manager.py
"""
Intent Manager
- Wraps the existing NutritionQueryClassifier (query_classifier.py)
- Implements therapy gatekeeper (requires BOTH medications AND biomarkers)
- Produces a normalized classification dict used by the orchestrator
- Generates the therapy onboarding (3-option) message when therapy is downgraded
- Normalizes short responses like "step", "general", "overview", "upload"
"""

import logging
import re
from typing import Dict, Any, List, Optional

from app.components.query_classifier import NutritionQueryClassifier

logger = logging.getLogger(__name__)


# Short mappings accepted from UI (gradio inputs may be short)
_SHORT_OPTION_MAP = {
    "1": "upload",
    "2": "step_by_step",
    "3": "general_info_first",
    "upload": "upload",
    "upload lab": "upload",
    "lab": "upload",
    "photo": "upload",
    "pdf": "upload",
    "step": "step_by_step",
    "step by step": "step_by_step",
    "step-by-step": "step_by_step",
    "stepbystep": "step_by_step",
    "step_by_step": "step_by_step",
    "stepbystep": "step_by_step",
    "stepbystep.": "step_by_step",
    "general": "general_info_first",
    "overview": "general_info_first",
    "general info": "general_info_first",
    "general info first": "general_info_first",
    "general_info_first": "general_info_first",
    "1.": "upload",
    "2.": "step_by_step",
    "3.": "general_info_first",
}


class IntentManager:
    """
    Controller that uses NutritionQueryClassifier for intent detection and
    applies higher-level policy (therapy gatekeeper, graceful degradation).
    """

    def _init_(self, classifier: Optional[NutritionQueryClassifier] = None):
        self.classifier = classifier or NutritionQueryClassifier()
        logger.info("IntentManager initialized")

    def _normalize_short_option(self, text: str) -> Optional[str]:
        """Normalize user replies like 'step', 'general', 'upload' to canonical option keys."""
        if not text:
            return None
        t = text.strip().lower()
        t = re.sub(r'[^\w\s\-]', '', t)  # drop punctuation
        t = t.replace('_', ' ')
        # try direct map
        mapped = _SHORT_OPTION_MAP.get(t)
        if mapped:
            return mapped
        # try word-based heuristics
        if "upload" in t or "lab" in t or "photo" in t or "pdf" in t:
            return "upload"
        if "step" in t:
            return "step_by_step"
        if "overview" in t or "general" in t:
            return "general_info_first"
        return None

    def _diagnosis_key_for_biomarkers(self, diagnosis: Optional[str]) -> List[str]:
        """
        Return a short list of example biomarkers relevant to diagnosis for user education.
        This mirrors / references the chat_orchestrator's _get_diagnosis_specific_biomarkers logic.
        """
        if not diagnosis:
            return ["creatinine", "eGFR", "HbA1c", "albumin"]

        d = diagnosis.lower()
        if "ckd" in d or "kidney" in d or "renal" in d:
            return ["creatinine", "eGFR", "potassium", "phosphorus", "albumin"]
        if "diabetes" in d or "t1d" in d or "type 1" in d:
            return ["HbA1c", "fasting glucose", "c-peptide (if available)"]
        if "epilepsy" in d:
            return ["vitamin D", "folate", "vitamin B12", "drug levels (if on AEDs)"]
        if "cystic" in d or "cf" in d:
            return ["Vitamins A/D/E/K", "albumin", "prealbumin"]
        if "preterm" in d or "neonate" in d:
            return ["albumin", "calcium", "phosphate", "ALP", "weight gain"]
        if "pku" in d or "phenylketonuria" in d or "msud" in d or "galactose" in d:
            return ["specific amino acids (phenylalanine, leucine)", "amino acid profile"]
        if "food allergy" in d or "allergy" in d:
            return ["IgE (if available)", "eosinophils (if available)"]
        if "ibd" in d or "crohn" in d or "gastro" in d:
            return ["albumin", "CRP", "iron indices"]
        # default
        return ["creatinine", "eGFR", "HbA1c", "albumin"]

    def classify_and_enforce(self, query: str) -> Dict[str, Any]:
        """
        Main entry point.
        Returns a dictionary with:
            - original_label, final_label, confidence
            - diagnosis, medications, biomarkers, biomarkers_detailed
            - downgraded (bool), downgrade_reason (str)
            - onboarding_message (if downgraded from therapy to recommendation)
        """
        logger.debug(f"Classifying query: {query[:200]}")
        base = self.classifier.classify(query)

        original_label = base.get("label", "general")
        confidence = base.get("confidence", 0.0)
        diagnosis = base.get("diagnosis")
        meds = base.get("medications") or []
        biomarkers = base.get("biomarkers") or []
        biomarkers_detailed = base.get("biomarkers_detailed") or {}

        final_label = original_label
        downgraded = False
        downgrade_reason = None
        onboarding_message = None

        # Apply classifier-level gatekeeper (use classifier.enforce_gatekeeper if available)
        try:
            forced = self.classifier.enforce_gatekeeper(query, original_label, confidence)
            if forced != original_label:
                logger.info(f"Gatekeeper changed label from {original_label} -> {forced}")
                final_label = forced
                downgraded = True
                downgrade_reason = f"gatekeeper_forced_{forced}"
        except Exception as e:
            logger.debug(f"enforce_gatekeeper unavailable or failed: {e}")

        # Therapy gatekeeper enforcement (CRITICAL)
        if final_label == "therapy":
            has_meds = len(meds) > 0
            has_biomarkers = len(biomarkers) > 0 or bool(biomarkers_detailed)
            logger.debug(f"therapy check: has_meds={has_meds}, has_biomarkers={has_biomarkers}")
            if not (has_meds and has_biomarkers):
                # Downgrade to recommendation (non-negotiable)
                logger.warning("Therapy requested but missing medications or biomarkers — downgrading to 'recommendation'")
                final_label = "recommendation"
                downgraded = True
                missing = []
                if not has_meds:
                    missing.append("medications")
                if not has_biomarkers:
                    missing.append("biomarkers")
                downgrade_reason = f"missing_{'_'.join(missing)}"

                # Build the onboarding/nudge message describing options (uses user's diagnosis for wording)
                required_bms = self._diagnosis_key_for_biomarkers(diagnosis)
                required_bms_text = ", ".join(required_bms[:6])
                diagnosis_name = diagnosis or "this condition"
                onboarding_message = self._build_onboarding_message(diagnosis_name, required_bms_text, len(missing))

                # Log for debugging
                logger.info(f"Downgraded therapy -> recommendation. Missing: {missing}")

        # Low-confidence overrides (already partly handled by classifier)
        if not downgraded and final_label == "therapy" and confidence < 0.78:
            logger.warning("Therapy label with low confidence - downgrading to recommendation")
            final_label = "recommendation"
            downgraded = True
            downgrade_reason = "low_confidence"

        # Construct normalized result
        result = {
            "original_label": original_label,
            "final_label": final_label,
            "confidence": confidence,
            "diagnosis": diagnosis,
            "medications": meds,
            "biomarkers": biomarkers,
            "biomarkers_detailed": biomarkers_detailed,
            "downgraded": downgraded,
            "downgrade_reason": downgrade_reason,
            "onboarding_message": onboarding_message,
            # keep full classifier payload for downstream use
            "raw_classifier": base
        }

        return result

    def _build_onboarding_message(self, diagnosis: str, biomarker_examples: str, missing_count: int) -> str:
        """
        Returns the three-option onboarding message (nudge) when therapy cannot be done.
        Matches the user's requested format (markdown-like).
        """
        # Note: len(missing_items) used earlier by UI; we keep message generic
        message = (
            f"How would you like to proceed?\n\n"
            f"📋 Option 1: Upload Lab Results (Fastest)\n"
            f"   Upload a PDF or photo of recent lab report. I'll extract biomarker values automatically.\n"
            f"   → Click [Upload Lab Results] button below ↓\n\n"
            f"✍ Option 2: Answer Step-by-Step ({missing_count} questions)    "
            f"I'll ask one question at a time (age, medications, labs, etc.)    Takes a few seconds.    → Type \"step by step\"\n\n"
            f"📚 Option 3: General {diagnosis or 'Diet'} Information First\n"
            f"   Get general diet guidelines for {diagnosis or 'this condition'} while you gather clinical data, then come back for personalized therapy.\n"
            f"   → Type \"general info first\"\n\n"
            f"*Examples of biomarkers I typically need:* {biomarker_examples}\n\n"
            f"Which option works best for you?\n\n"
            f"---\n"
            f"⚠ For educational purposes only. Not medical advice. Consult a healthcare provider."
        )
        return message

    def normalize_user_option_reply(self, user_reply: str) -> Optional[str]:
        """
        Convert a free-text user reply into canonical onboarding action:
        -> "upload" | "step_by_step" | "general_info_first" | None
        """
        return self._normalize_short_option(user_reply)


# Example usage:
# im = IntentManager()
# out = im.classify_and_enforce("Therapy for my 6 year old with epilepsy")
# if out["downgraded"]:
#     send out["onboarding_message"] to UI and await normalized option from normalize_user_option_reply()