# app/components/llm_response_manager.py
"""
LLMResponseManager

Implements the 12-step blueprint for classification -> retrieval -> computation -> response generation.
Depends on available components:
- app.components.query_classifier.NutritionQueryClassifier
- app.components.followup_question_generator.FollowUpQuestionGenerator
- app.components.hybrid_retriever (filtered_retrieval)
- app.components.computation_manager.ComputationManager
- app.components.dri_loader.DRILoader (via ComputationManager)
- app.components.nutrient_calculator (optimize_diet, convert_fct_rows_to_foods) for meal plans

Stateful per-session slot store is included to avoid requiring SlotManager at this stage.

Enhanced with:
- Thread-safe session management (from session_manager.py)
- Session timeout and cleanup
- Schema-based slot validation (from ambiguity_gate.py + slot_schema.py)
"""
from typing import Dict, Any, List, Optional, Tuple
import logging
import math
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.components.query_classifier import NutritionQueryClassifier
from app.components.followup_question_generator import FollowUpQuestionGenerator
from app.components.hybrid_retriever import filtered_retrieval, retriever
from app.components.computation_manager import ComputationManager
from app.components.therapy_generator import TherapyGenerator
from app.components.fct_manager import FCTManager
from app.components.meal_plan_generator import MealPlanGenerator
from app.components.citation_manager import CitationManager
from app.components.profile_summary_card import ProfileSummaryCard

logger = logging.getLogger(__name__)

# -------------------------
# Slot Validation Schema (from slot_schema.py)
# -------------------------
@dataclass
class SlotSpec:
    """Slot specification for validation"""
    name: str
    type: str  # "string","enum","number","list","dict","bool"
    required: bool
    enum: Optional[List[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    hint: Optional[str] = None

# Supported therapy conditions (strict list)
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
    "galactosemia": "Galactosemia",
    "epilepsy": "Epilepsy",
    "ketogenic therapy": "Epilepsy / Ketogenic Therapy",
    "chronic kidney disease": "Chronic Kidney Disease",
    "ckd": "Chronic Kidney Disease",
    "gi disorders": "GI Disorders",
    "ibd": "GI Disorders",
    "gerd": "GI Disorders",
    "gastroesophageal reflux": "GI Disorders"
}

class LLMResponseManager:
    def __init__(self, dri_table_path: str = "data/dri_table.csv"):
        # Core components
        self.classifier = NutritionQueryClassifier()
        self.followup_gen = FollowUpQuestionGenerator()
        self.computation = ComputationManager(dri_table_path)

        # Therapy flow components (Phase 7)
        self.therapy_gen = TherapyGenerator()
        self.fct_mgr = FCTManager()
        self.meal_plan_gen = MealPlanGenerator()

        # Per-session state with thread safety
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._session_lock = threading.RLock()  # Thread-safe
        self._session_timeout = timedelta(hours=24)  # Session expires after 24 hours

        # Default session ID for single-session use (backward compatibility)
        self.default_session_id = "default"

        # Slot schemas for validation (from slot_schema.py)
        self.slot_schemas = {
            "therapy": [
                SlotSpec("diagnosis", "string", True, hint="Medical condition"),
                SlotSpec("age", "number", True, min=0, max=120, hint="Age in years"),
                SlotSpec("medications", "list", True, hint="List of medications"),
                SlotSpec("biomarkers", "dict", True, hint="Lab results with values"),
                SlotSpec("weight_kg", "number", True, min=2, max=400),
                SlotSpec("height_cm", "number", True, min=30, max=250),
                SlotSpec("country", "string", False),
                SlotSpec("allergies", "list", False),
            ],
            "recommendation": [
                SlotSpec("age", "number", True, min=0, max=120),
                SlotSpec("diagnosis", "string", False),
                SlotSpec("weight_kg", "number", False, min=2, max=400),
                SlotSpec("height_cm", "number", False, min=30, max=250),
                SlotSpec("country", "string", False),
                SlotSpec("allergies", "list", False),
            ],
            "comparison": [
                SlotSpec("food_a", "string", True),
                SlotSpec("food_b", "string", True),
                SlotSpec("country", "string", False),
            ],
            "general": []
        }

    # -------------------------
    # Session helpers (Thread-safe with timeout)
    # -------------------------
    def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Get or create session with thread safety and timeout check"""
        with self._session_lock:  # Thread-safe
            if session_id not in self.sessions:
                # Initialize new session
                self.sessions[session_id] = {
                    "slots": {},            # age, sex, weight_kg, height_cm, diagnosis, medications, biomarkers, country, allergies, etc.
                    "lab_results": [],      # parsed labs (if user uploaded)
                    "last_query_info": None,
                    "clarifications": {},   # e.g., {"mode":"step_by_step"}
                    "created_at": datetime.utcnow(),       # Session creation time
                    "last_accessed": datetime.utcnow(),   # Last access time
                }

            session = self.sessions[session_id]

            # Check if session expired
            if datetime.utcnow() - session.get("last_accessed", datetime.utcnow()) > self._session_timeout:
                logger.info(f"Session {session_id} expired, resetting")
                self.sessions[session_id] = {
                    "slots": {},
                    "lab_results": [],
                    "last_query_info": None,
                    "clarifications": {},
                    "created_at": datetime.utcnow(),
                    "last_accessed": datetime.utcnow(),
                }
                session = self.sessions[session_id]

            # Update last accessed time
            session["last_accessed"] = datetime.utcnow()

            return session

    # -------------------------
    # Step 1: classify query
    # -------------------------
    def classify_query(self, session_id: str, query: str) -> Dict[str, Any]:
        """
        Returns classifier result and stores it in session.
        """
        session = self._get_session(session_id)
        result = self.classifier.classify(query)
        session["last_query_info"] = result
        logger.debug(f"Classified query: {result}")
        return result

    # -------------------------
    # Step 2: extract entities (lightweight helpers using classifier)
    # -------------------------
    def extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Use classifier helper methods (available) to pull diagnosis, biomarkers, medications, country.
        Also extracts age, weight, height using regex patterns.
        Returns a small dict of extracted entities.
        """
        import re

        ent = {
            "diagnosis": self.classifier._extract_diagnosis(query),
            "biomarkers_detailed": self.classifier.extract_biomarkers_with_values(query),
            "biomarkers": self.classifier.extract_biomarkers(query),
            "medications": self.classifier.extract_medications(query),
            "country": self.classifier._extract_country(query),
        }

        # CRITICAL FIX: Extract age (missing from original implementation)
        # Patterns: "7 years old", "7yo", "7 y/o", "7-year-old", "age 7", "7 year old"
        age_patterns = [
            r'(\d+\.?\d*)\s*(?:years?\s+old|y/?o|year[\s-]old)',
            r'age\s+(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*y\b',  # "7y"
        ]
        for pattern in age_patterns:
            match = re.search(pattern, query.lower())
            if match:
                try:
                    age = float(match.group(1))
                    if 0 < age <= 18:  # Pediatric range validation
                        ent["age"] = int(age) if age == int(age) else age
                        logger.debug(f"Extracted age: {ent['age']}")
                        break
                except (ValueError, IndexError):
                    pass

        # Extract weight: "70kg", "70 kg", "weighs 70 kg", "weight: 70kg"
        weight_patterns = [
            r'(\d+\.?\d*)\s*kg\b',
            r'weight[:\s]+(\d+\.?\d*)\s*(?:kg)?',
            r'weighs?\s+(\d+\.?\d*)\s*(?:kg)?',
        ]
        for pattern in weight_patterns:
            match = re.search(pattern, query.lower())
            if match:
                try:
                    weight = float(match.group(1))
                    if 1 < weight < 200:  # Sanity check
                        ent["weight_kg"] = weight
                        logger.debug(f"Extracted weight: {weight}kg")
                        break
                except (ValueError, IndexError):
                    pass

        # Extract height: "175cm", "175 cm", "height 175cm", "1.75m", "1.75 m"
        height_patterns = [
            r'(\d+\.?\d*)\s*cm\b',
            r'(\d+\.\d+)\s*m\b',  # meters
            r'height[:\s]+(\d+\.?\d*)\s*(?:cm)?',
        ]
        for pattern in height_patterns:
            match = re.search(pattern, query.lower())
            if match:
                try:
                    height = float(match.group(1))
                    # Convert meters to cm if needed
                    if height < 3:  # Likely in meters
                        height = height * 100
                    if 30 < height < 250:  # Sanity check
                        ent["height_cm"] = height
                        logger.debug(f"Extracted height: {height}cm")
                        break
                except (ValueError, IndexError):
                    pass

        return ent

    # -------------------------
    # Utility: BMI / WFL calculation
    # -------------------------
    def compute_bmi_or_wfl(self, age_years: Optional[float], weight_kg: Optional[float], height_cm: Optional[float], is_preterm: bool = False) -> Dict[str, Any]:
        """
        If age >= 2: compute BMI, BMI percentile not calculated here (needs growth charts)
        If age < 2: return weight-for-length (kg per m) and guidance note.
        Preterm: add note that corrected age/growth charts should be used.
        """
        out = {}
        if weight_kg is None or (height_cm is None and (age_years is None or age_years >= 2)):
            out["note"] = "Insufficient anthropometry for BMI/WFL calculation."
            return out

        if age_years is not None and age_years < 2:
            # weight-for-length approximation (kg / m)
            if height_cm is None or height_cm <= 0:
                out["note"] = "Height missing or invalid for weight-for-length."
                return out
            length_m = height_cm / 100.0
            wfl = weight_kg / length_m  # kg per meter - not a percentile but can signal issues
            out["weight_for_length_value"] = round(wfl, 3)
            out["interpretation"] = "Weight-for-length computed. Use WHO growth charts to determine percentile."
            if is_preterm:
                out["preterm_note"] = "This is a preterm infant — use corrected age and NICU growth charts for interpretation."
            return out
        else:
            # BMI
            if height_cm is None or height_cm <= 0:
                out["note"] = "Height missing or invalid for BMI."
                return out
            height_m = height_cm / 100.0
            bmi = weight_kg / (height_m * height_m)
            out["bmi"] = round(bmi, 2)

            # rudimentary classification using CDC adult-like cutoffs adapted for pediatrics (note: true pediatric uses percentile)
            if age_years is not None and age_years >= 2:
                # For simplicity provide WHO/CDC hints but warn that percentile is required.
                if bmi < 14:  # heuristic lower bound
                    cat = "Underweight (heuristic)"
                elif bmi < 18.5:
                    cat = "Normal weight (heuristic)"
                elif bmi < 25:
                    cat = "Overweight (heuristic)"
                else:
                    cat = "Obesity (heuristic)"
                out["category_hint"] = cat
                out["note"] = "This is a heuristic category. For pediatric patients use BMI-for-age percentiles (WHO/CDC)."
            else:
                out["note"] = "Age not provided; BMI computed but pediatric percentile check requires age."
            if is_preterm:
                out["preterm_note"] = "For preterm infants, use corrected age for BMI/growth assessment."
            return out

    # -------------------------
    # Routing: main entry point
    # -------------------------
    def handle_user_query(self, session_id: str, user_query: str) -> Dict[str, Any]:
        """
        Main orchestrator entry for each user message.
        Returns a structured response dict that front-end/DialogManager can interpret.

        CRITICAL FIX (APPROACH 1): Extract entities FIRST, then handle followup state.
        This allows opportunistic data capture even when awaiting a slot.
        """
        session = self._get_session(session_id)

        # APPROACH 1: ALWAYS extract entities first (even in followup mode)
        # This prevents data loss when user volunteers information during followup
        entities = self.extract_entities(user_query)
        # Merge entities into session slots if present
        for k, v in entities.items():
            if v:
                if k == "biomarkers_detailed":
                    # merge dicts
                    existing = session["slots"].get("biomarkers_detailed", {})
                    existing.update(v)
                    session["slots"]["biomarkers_detailed"] = existing
                elif k == "biomarkers":
                    existing = session["slots"].get("biomarkers", [])
                    for b in v:
                        if b not in existing:
                            existing.append(b)
                    session["slots"]["biomarkers"] = existing
                elif k == "medications":
                    existing = session["slots"].get("medications", [])
                    for m in v:
                        if m not in existing:
                            existing.append(m)
                    session["slots"]["medications"] = existing
                else:
                    session["slots"].setdefault(k, v)

        # THEN check if we're awaiting a followup response
        awaiting_slot = session.get("awaiting_slot")
        if awaiting_slot:
            logger.info(f"Detected followup context - awaiting slot: {awaiting_slot}")
            # Route to followup handler
            result = self.handle_followup_response(session_id, user_query, awaiting_slot)

            # Check if slot was filled or rejected
            if result["status"] == "slot_filled":
                # Clear awaiting state
                session.pop("awaiting_slot", None)
                # Re-run the pipeline with last query to continue flow
                last_query = session.get("last_raw_query", "")
                if last_query:
                    logger.info(f"Slot filled, re-running pipeline with original query: {last_query}")
                    return self.handle_user_query(session_id, last_query)
                else:
                    return {"status": "slot_filled", "message": f"Updated {awaiting_slot}"}
            elif result["status"] == "slot_not_filled":
                # Handle rejection
                reason = result.get("details", {}).get("reason")
                if reason == "user_rejected":
                    # User said "no" - mark slot as explicitly rejected
                    logger.info(f"User rejected slot {awaiting_slot}, marking as rejected")
                    session.pop("awaiting_slot", None)
                    # Mark slot as rejected (use special marker to distinguish from missing)
                    session["slots"][f"_rejected_{awaiting_slot}"] = True
                    session["slots"][awaiting_slot] = "user_declined"  # Mark as declined

                    # Re-run the pipeline to ask for next slot or continue
                    last_query = session.get("last_raw_query", "")
                    if last_query:
                        logger.info(f"Re-running pipeline after rejection to get next question")
                        return self.handle_user_query(session_id, last_query)
                    else:
                        return {"status": "acknowledged", "message": "Continuing without that information"}
                else:
                    # Unclear response - ask again with clarification
                    return {"status": "needs_clarification", "message": f"I didn't understand. {session.get('last_followup_question', 'Please try again.')}"}
            else:
                return result

        # 1) classify
        query_info = self.classify_query(session_id, user_query)
        label = query_info.get("label", "general")
        session["last_query_info"] = query_info
        session["last_raw_query"] = user_query  # CRITICAL: Store for re-run after followup

        # 2) Entity extraction and merging already done above (moved before followup check)

        # 3) route based on label
        if label == "comparison":
            return self._handle_comparison(session_id, user_query, session, query_info)
        elif label == "recommendation":
            return self._handle_recommendation(session_id, user_query, session, query_info)
        elif label == "therapy":
            return self._handle_therapy(session_id, user_query, session, query_info)
        else:
            return self._handle_general(session_id, user_query, session, query_info)

    # -------------------------
    # Comparison handler
    # -------------------------
    def _handle_comparison(self, session_id: str, query: str, session: Dict[str, Any], query_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dual logic:
         - If food vs food -> do FCT retrieval + numeric comparison
         - Else -> conceptual/knowledge comparison via retrieval from corpus
        """
        # Attempt to detect two food names via a simple heuristic: look for "vs" or "compare" or two food tokens extracted by retrieval
        q_lower = query.lower()
        food_candidates = []

        # Try to find named foods by hitting the retriever with short queries for nouns in the query
        # We'll attempt a few likely tokens (words >3 chars)
        tokens = [t for t in q_lower.replace(",", " ").split() if len(t) > 3]
        # test top tokens for being food by retrieving FCT-like docs
        for tok in tokens[:8]:
            try:
                docs = filtered_retrieval(tok, {"doc_type": "FCT"}, k=3)
            except Exception:
                docs = []
            if docs:
                # treat tok as a possible food
                food_candidates.append(tok)

        # If explicit "compare X and Y" patterns, try to extract two nouns after compare/ vs
        import re
        m = re.search(r'compare\s+([a-z0-9\s\-]+?)\s+(and|vs|versus)\s+([a-z0-9\s\-]+)', q_lower)
        if m:
            food_candidates = [m.group(1).strip(), m.group(3).strip()]

        # If we have two foods, do nutrient comparison
        if len(food_candidates) >= 2:
            food_a, food_b = food_candidates[0], food_candidates[1]
            # Retrieve more precise FCT rows for each
            rows_a = filtered_retrieval(food_a, {"doc_type": "FCT", "food": food_a}, k=10)
            rows_b = filtered_retrieval(food_b, {"doc_type": "FCT", "food": food_b}, k=10)
            # If retriever returns Document objects, extract page_content or metadata (depends on vector store schema).
            def rows_to_simple(rows):
                simple = []
                for d in rows or []:
                    # support both doc.page_content and metadata/content
                    text = getattr(d, "page_content", None) or d.metadata.get("text") or d.metadata.get("content", "")
                    title = d.metadata.get("title") or d.metadata.get("food") or ""
                    simple.append({"title": title, "text": text, "doc": d})
                return simple

            simple_a = rows_to_simple(rows_a)
            simple_b = rows_to_simple(rows_b)

            # Build a compact comparison result (we avoid heavy numeric parsing here; front-end can request tables)
            summary = {
                "query_type": "comparison",
                "mode": "food_vs_food",
                "food_a": food_a,
                "food_b": food_b,
                "results_a_count": len(simple_a),
                "results_b_count": len(simple_b),
                "summary_text": f"Found {len(simple_a)} FCT entries for '{food_a}' and {len(simple_b)} for '{food_b}'. Use 'detailed table' action to retrieve a nutrient-by-nutrient comparison.",
                "followup": "Would you like a detailed nutrient table per 100 g, or a ranked nutrient summary?"
            }
            return {"status": "ok", "payload": summary}

        # Else, treat as knowledge comparison
        # Use retrieval to fetch texts about the two concepts mentioned
        # Simple heuristic: split around ' vs ' or ' compare ' or ' between '
        if " vs " in q_lower or " versus " in q_lower or " compare " in q_lower or " between " in q_lower:
            # try full query retrieval
            docs = filtered_retrieval(query, {"doc_type": "clinical_text"}, k=5) or filtered_retrieval(query, {}, k=5)
            snippets = []
            for d in docs or []:
                snippets.append({
                    "title": getattr(d, "metadata", {}).get("chapter_title", ""),
                    "source": getattr(d, "metadata", {}).get("book_title", ""),
                    "text_snippet": (d.page_content[:400] if getattr(d, "page_content", None) else "")
                })
            payload = {
                "query_type": "comparison",
                "mode": "knowledge_comparison",
                "snippets": snippets,
                "summary_text": "Retrieved relevant sections to compare the requested concepts.",
                "followup": "Would you like summarized contrasts, source citations, or direct quotes?"
            }
            return {"status": "ok", "payload": payload}

        # Fallback
        return {"status": "need_clarification", "message": "I couldn't identify two foods or clear comparison targets. Do you mean two foods, two nutrients, or two conditions?"}

    # -------------------------
    # Recommendation handler
    # -------------------------
    def _handle_recommendation(self, session_id: str, query: str, session: Dict[str, Any], query_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provide nutrient targets and food sources (not calculated to target).
        Ask needed follow-ups if missing.
        """
        # Determine missing slots
        followup = self.followup_gen.generate_follow_up_question(query_info, session.get("slots"), session.get("lab_results"), session.get("clarifications"))
        if followup:
            # CRITICAL: Store awaiting slot in session to detect followup responses
            session["awaiting_slot"] = followup.get("slot")
            session["last_followup_question"] = followup.get("question")
            logger.info(f"Asking followup for slot: {followup.get('slot')}")
            return {"status": "needs_slot", "followup": followup}

        # All required slots present - compute DRI targets
        slots = session["slots"]
        age = float(slots.get("age")) if slots.get("age") is not None else None
        sex = slots.get("sex") or slots.get("gender") or "F"
        # ensure sex format
        sex = sex[0].upper()

        # Compute BMI/WFL if anthropometry present
        bmi_info = self.compute_bmi_or_wfl(age, slots.get("weight_kg"), slots.get("height_cm"), is_preterm=slots.get("is_preterm", False))
        # Get micronutrient targets
        micronutrients = self.computation.get_micronutrient_targets(int(age) if age is not None else 0, sex)

        # For main nutrients, retrieve representative food sources (not a calculated diet)
        # We'll query retriever for each of the top nutrients (protein, calcium, iron, vitamin_d, zinc)
        nutrients_to_show = ["protein", "calcium", "iron", "vitamin_d", "zinc", "folate", "vitamin_c"]
        food_sources = {}
        for n in nutrients_to_show:
            q = f"food sources of {n}"
            try:
                docs = filtered_retrieval(q, {"doc_type": "FCT", "country": slots.get("country")}, k=5)
            except Exception:
                docs = []
            food_sources[n] = []
            for d in docs or []:
                title = getattr(d, "metadata", {}).get("food") or getattr(d, "metadata", {}).get("chapter_title") or ""
                # if no clear food name, push snippet
                snippet = (d.page_content[:200] if getattr(d, "page_content", None) else "")
                food_sources[n].append({"title": title, "snippet": snippet})

        payload = {
            "query_type": "recommendation",
            "bmi_info": bmi_info,
            "micronutrient_targets": micronutrients,
            "food_sources": food_sources,
            "summary_text": "Provided DRI-based nutrient targets and representative food sources. This is NOT a therapeutic diet."
        }
        return {"status": "ok", "payload": payload}

    # -------------------------
    # Therapy handler
    # -------------------------
    def _handle_therapy(self, session_id: str, query: str, session: Dict[str, Any], query_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Therapy must be limited to the supported conditions. Requires medications + biomarkers (gatekeeper).
        If unsupported condition -> downgrade to recommendation and inform user.
        After all follow-ups answered:
          - compute therapeutic nutrient targets (via retrieval + DRI)
          - fetch food sources matching those targets (FCT)
          - ask user: "Generate 3-day therapeutic meal plan?" -> on consent call optimization
        """
        # Extract diagnosis (prefer session slot if already set)
        diagnosis = session["slots"].get("diagnosis") or query_info.get("diagnosis")
        if diagnosis:
            diag_key = diagnosis.lower()
            supported = None
            for k in SUPPORTED_THERAPY_CONDITIONS:
                if k in diag_key:
                    supported = SUPPORTED_THERAPY_CONDITIONS[k]
                    break
            if not supported:
                # Downgrade to recommendation
                msg = {
                    "status": "downgraded",
                    "reason": "unsupported_condition",
                    "message": (
                        "Therapeutic diet generation is only available for the following conditions: "
                        "Preterm Nutrition; Type 1 Diabetes; Food Allergy; Cystic Fibrosis; "
                        "Inherited Metabolic Disorders (PKU, MSUD, Galactosemia); Epilepsy/Ketogenic Therapy; "
                        "Chronic Kidney Disease; GI Disorders (IBD/GERD). "
                        "I will provide DRI-based recommendations instead. "
                    )
                }
                # proceed with recommendation flow
                rec = self._handle_recommendation(session_id, query, session, query_info)
                msg["recommendation_payload"] = rec
                return msg
        else:
            # missing diagnosis slot -> ask followup
            followup = self.followup_gen.generate_follow_up_question(query_info, session.get("slots"), session.get("lab_results"), session.get("clarifications"))
            # CRITICAL: Store awaiting slot in session
            session["awaiting_slot"] = followup.get("slot")
            session["last_followup_question"] = followup.get("question")
            logger.info(f"Asking followup for slot: {followup.get('slot')}")
            return {"status": "needs_slot", "followup": followup}

        # Now ensure required clinical slots are present: medications, biomarkers (or lab_results), age/anthro, country
        followup = self.followup_gen.generate_follow_up_question(query_info, session.get("slots"), session.get("lab_results"), session.get("clarifications"))
        if followup:
            # CRITICAL: Store awaiting slot in session
            session["awaiting_slot"] = followup.get("slot")
            session["last_followup_question"] = followup.get("question")
            logger.info(f"Asking followup for slot: {followup.get('slot')}")
            return {"status": "needs_slot", "followup": followup}

        # CRITICAL GATEKEEPER: Therapy requires BOTH medications AND biomarkers
        slots = session["slots"]
        meds = slots.get("medications")
        biomarkers_detailed = slots.get("biomarkers_detailed", {})
        lab_results = session.get("lab_results", [])

        # Check if medications are actually provided (not declined/empty)
        has_meds = (
            meds and
            meds != "user_declined" and
            not (isinstance(meds, list) and len(meds) == 0) and
            not slots.get("_rejected_medications")
        )

        # Check if biomarkers are actually provided
        has_biomarkers = (
            (bool(biomarkers_detailed) or bool(lab_results)) and
            not slots.get("_rejected_biomarkers")
        )

        logger.info(f"Therapy gatekeeper check: has_meds={has_meds}, has_biomarkers={has_biomarkers}")

        if not (has_meds and has_biomarkers):
            # CRITICAL: Downgrade to recommendation if missing either requirement
            missing = []
            if not has_meds:
                missing.append("medications")
            if not has_biomarkers:
                missing.append("biomarkers")

            logger.warning(f"Therapy gatekeeper FAILED - missing: {missing}. Downgrading to recommendation.")

            msg = {
                "status": "downgraded",
                "reason": f"missing_{'_and_'.join(missing)}",
                "message": (
                    f"Therapeutic meal planning requires both medications AND biomarker data. "
                    f"Missing: {', '.join(missing)}. "
                    f"I will provide general dietary recommendations instead."
                )
            }
            # Downgrade to recommendation flow
            rec = self._handle_recommendation(session_id, query, session, query_info)
            msg["recommendation_payload"] = rec
            return msg

        # ============================================================================
        # ALL REQUIRED SLOTS PRESENT -> START 7-STEP THERAPY FLOW
        # ============================================================================
        slots = session["slots"]
        age = int(slots.get("age")) if slots.get("age") is not None else None
        sex = slots.get("sex", "F")[0].upper()
        weight = slots.get("weight_kg")
        height = slots.get("height_cm")
        meds = slots.get("medications", [])
        biomarkers = session.get("lab_results") or slots.get("biomarkers_detailed", {})
        country = slots.get("country", "Kenya")  # Default to Kenya
        allergies = slots.get("allergies", [])
        activity_level = slots.get("activity_level", "moderate")

        # Normalize diagnosis to canonical name
        therapy_area = None
        for k, v in SUPPORTED_THERAPY_CONDITIONS.items():
            if k in diagnosis.lower():
                therapy_area = v
                diagnosis = v  # Use canonical name
                break

        logger.info(f"Starting 7-step therapy flow for {diagnosis} (age={age}, sex={sex}, weight={weight}kg, height={height}cm)")

        # Initialize Citation Manager for this therapy flow
        citations = CitationManager()

        # Initialize Profile Summary Card
        patient_info = {
            "age": age,
            "sex": sex,
            "weight_kg": weight,
            "height_cm": height,
            "diagnosis": diagnosis,
            "medications": meds,
            "biomarkers": biomarkers,
            "country": country,
            "allergies": allergies
        }
        card = ProfileSummaryCard.initialize_card(patient_info)

        # ============================================================================
        # STEP 1: GET BASELINE DRI REQUIREMENTS
        # ============================================================================
        logger.info("STEP 1: Getting baseline DRI requirements")
        try:
            baseline_dri = self.computation.get_dri_baseline_with_energy(
                age, sex, weight, height, activity_level
            )
            card.update_step(1, baseline_dri)
            citations.add_citation(
                source="WHO/FAO DRI",
                context=f"Baseline requirements for age {age}, sex {sex}",
                source_type="dri"
            )
            logger.info(f"STEP 1 complete: {len(baseline_dri)} baseline nutrients retrieved")
        except Exception as e:
            logger.error(f"STEP 1 failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to retrieve baseline DRI requirements: {str(e)}"
            }

        # ============================================================================
        # STEP 2: GET THERAPEUTIC ADJUSTMENTS
        # ============================================================================
        logger.info("STEP 2: Getting therapeutic adjustments from Clinical Paediatric Dietetics")
        try:
            therapeutic_adjustments = self.therapy_gen.get_therapeutic_adjustments(
                diagnosis=diagnosis,
                baseline_dri=baseline_dri,
                age=age,
                weight=weight
            )
            card.update_step(2, therapeutic_adjustments)

            # Extract citations from adjustments
            for nutrient, details in therapeutic_adjustments.items():
                if details.get("source"):
                    citations.add_citation(
                        source=details["source"],
                        context=f"{nutrient} adjustment for {diagnosis}",
                        source_type="clinical"
                    )

            logger.info(f"STEP 2 complete: {len(therapeutic_adjustments)} nutrients adjusted")
        except Exception as e:
            logger.error(f"STEP 2 failed: {e}")
            # Continue with baseline if adjustments fail
            therapeutic_adjustments = baseline_dri
            logger.warning("Using baseline DRI as fallback for therapeutic adjustments")

        # ============================================================================
        # STEP 3: GET BIOCHEMICAL CONTEXT
        # ============================================================================
        logger.info("STEP 3: Getting biochemical context from Integrative Human Biochemistry")
        try:
            affected_nutrients = list(therapeutic_adjustments.keys())
            biochemical_context = self.therapy_gen.get_biochemical_context(
                diagnosis=diagnosis,
                affected_nutrients=affected_nutrients
            )
            card.update_step(3, biochemical_context)
            citations.add_citation(
                source="Integrative Human Biochemistry",
                context=f"Metabolic pathways for {diagnosis}",
                source_type="biochemical"
            )
            logger.info(f"STEP 3 complete: Biochemical context retrieved")
        except Exception as e:
            logger.error(f"STEP 3 failed: {e}")
            biochemical_context = f"Biochemical context for {diagnosis} could not be retrieved."

        # ============================================================================
        # STEP 4: CALCULATE DRUG-NUTRIENT INTERACTIONS
        # ============================================================================
        logger.info("STEP 4: Calculating drug-nutrient interactions")
        try:
            drug_nutrient_interactions = self.therapy_gen.calculate_drug_nutrient_interactions(
                medications=meds,
                adjusted_requirements=therapeutic_adjustments
            )
            card.update_step(4, drug_nutrient_interactions)
            citations.add_citation(
                source="Drug-Nutrient Interactions Handbook",
                context=f"Interactions for {len(meds)} medications",
                source_type="drug_nutrient"
            )
            logger.info(f"STEP 4 complete: {len(drug_nutrient_interactions)} interactions found")
        except Exception as e:
            logger.error(f"STEP 4 failed: {e}")
            drug_nutrient_interactions = []
            logger.warning("No drug-nutrient interactions found")

        # ============================================================================
        # STEP 5: GET FOOD SOURCES FOR REQUIREMENTS
        # ============================================================================
        logger.info(f"STEP 5: Getting food sources from FCT for country: {country}")
        try:
            food_sources = self.fct_mgr.get_food_sources_for_requirements(
                therapeutic_requirements=therapeutic_adjustments,
                country=country,
                diagnosis=diagnosis,
                allergies=allergies,
                k=5
            )
            card.update_step(5, food_sources)

            # Add FCT citation
            fct_path = self.fct_mgr.get_fct_for_country(country)
            if fct_path:
                citations.add_citation(
                    source=fct_path,
                    context=f"Food sources for {country}",
                    source_type="fct"
                )

            logger.info(f"STEP 5 complete: Food sources for {len(food_sources)} nutrients")
        except Exception as e:
            logger.error(f"STEP 5 failed: {e}")
            food_sources = {}
            logger.warning("No food sources retrieved")

        # ============================================================================
        # DISPLAY PROFILE SUMMARY CARD (Steps 1-5 complete)
        # ============================================================================
        card_display = card.format_for_display()

        # ============================================================================
        # STEP 6: ASK ABOUT MEAL PLAN GENERATION
        # ============================================================================
        # Check if user has already indicated they want a meal plan
        wants_meal_plan = session.get("clarifications", {}).get("wants_meal_plan")

        if wants_meal_plan is None:
            # Ask user if they want a 3-day meal plan
            payload = {
                "status": "therapy_steps_1_to_5_complete",
                "diagnosis": diagnosis,
                "therapy_area": therapy_area,
                "profile_card": card_display,
                "baseline_dri": baseline_dri,
                "therapeutic_adjustments": therapeutic_adjustments,
                "biochemical_context": biochemical_context,
                "drug_nutrient_interactions": drug_nutrient_interactions,
                "food_sources": food_sources,
                "citations": citations.get_grouped_citations(),
                "message": (
                    "Therapeutic nutrient targets and food sources prepared. "
                    "Would you like me to generate a 3-day therapeutic meal plan? (Yes/No)"
                ),
                "awaiting_meal_plan_confirmation": True
            }
            # Store in session for next turn
            session["therapy_flow_state"] = {
                "card": card,
                "citations": citations,
                "baseline_dri": baseline_dri,
                "therapeutic_adjustments": therapeutic_adjustments,
                "biochemical_context": biochemical_context,
                "drug_nutrient_interactions": drug_nutrient_interactions,
                "food_sources": food_sources
            }
            return {"status": "ok", "payload": payload}

        elif wants_meal_plan:
            # ============================================================================
            # STEP 7: GENERATE 3-DAY MEAL PLAN
            # ============================================================================
            logger.info("STEP 7: Generating 3-day therapeutic meal plan")
            try:
                meal_plan = self.meal_plan_gen.generate_3day_plan(
                    therapeutic_requirements=therapeutic_adjustments,
                    food_sources=food_sources,
                    diagnosis=diagnosis,
                    medications=meds,
                    country=country
                )
                card.update_step(7, {"generated": True, "summary": meal_plan.get("summary")})
                meal_plan_display = self.meal_plan_gen.format_meal_plan_for_display(meal_plan)

                logger.info(f"STEP 7 complete: 3-day meal plan generated ({meal_plan['summary']['total_meals']} meals)")

                payload = {
                    "status": "therapy_complete",
                    "diagnosis": diagnosis,
                    "therapy_area": therapy_area,
                    "profile_card": card.format_for_display(),  # Updated with Step 7
                    "baseline_dri": baseline_dri,
                    "therapeutic_adjustments": therapeutic_adjustments,
                    "biochemical_context": biochemical_context,
                    "drug_nutrient_interactions": drug_nutrient_interactions,
                    "food_sources": food_sources,
                    "meal_plan": meal_plan,
                    "meal_plan_display": meal_plan_display,
                    "citations": citations.get_grouped_citations(),
                    "message": "7-step therapy flow complete. 3-day meal plan generated."
                }
                return {"status": "ok", "payload": payload}

            except Exception as e:
                logger.error(f"STEP 7 failed: {e}")
                payload = {
                    "status": "therapy_steps_1_to_5_complete",
                    "diagnosis": diagnosis,
                    "therapy_area": therapy_area,
                    "profile_card": card_display,
                    "baseline_dri": baseline_dri,
                    "therapeutic_adjustments": therapeutic_adjustments,
                    "biochemical_context": biochemical_context,
                    "drug_nutrient_interactions": drug_nutrient_interactions,
                    "food_sources": food_sources,
                    "citations": citations.get_grouped_citations(),
                    "message": f"Failed to generate meal plan: {str(e)}. Therapy flow steps 1-5 complete.",
                    "error": str(e)
                }
                return {"status": "ok", "payload": payload}

        else:
            # User declined meal plan - return Steps 1-5 results
            payload = {
                "status": "therapy_complete_no_meal_plan",
                "diagnosis": diagnosis,
                "therapy_area": therapy_area,
                "profile_card": card_display,
                "baseline_dri": baseline_dri,
                "therapeutic_adjustments": therapeutic_adjustments,
                "biochemical_context": biochemical_context,
                "drug_nutrient_interactions": drug_nutrient_interactions,
                "food_sources": food_sources,
                "citations": citations.get_grouped_citations(),
                "message": "Therapy flow complete (Steps 1-5). Meal plan not requested."
            }
            return {"status": "ok", "payload": payload}

    # -------------------------
    # General handler
    # -------------------------
    def _handle_general(self, session_id: str, query: str, session: Dict[str, Any], query_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Educational / definitional replies. Use retrieval to fetch the most relevant passages and synthesize a short answer.
        """
        try:
            docs = filtered_retrieval(query, {"doc_type": "clinical_text"}, k=5) or filtered_retrieval(query, {}, k=5)
        except Exception:
            docs = []

        snippets = []
        for d in docs or []:
            snippets.append({
                "title": getattr(d, "metadata", {}).get("chapter_title", ""),
                "source": getattr(d, "metadata", {}).get("book_title", ""),
                "text_snippet": (d.page_content[:500] if getattr(d, "page_content", None) else "")
            })

        payload = {
            "query_type": "general",
            "summary_text": "Educational answer synthesized from the corpus.",
            "snippets": snippets,
            "followup": "Would you like references, more depth, or practical suggestions?"
        }
        return {"status": "ok", "payload": payload}

    # -------------------------
    # Utility: accept follow-up answers (slot filling)
    # -------------------------
    def handle_followup_response(self, session_id: str, user_response: str, awaiting_slot: str) -> Dict[str, Any]:
        """
        Use the classifier's extract_from_followup_response to interpret a user response for a known awaiting slot.
        Update session slots and then re-run the main pipeline for the last query (if present).
        """
        from app.components.query_classifier import BIOMARKERS

        session = self._get_session(session_id)
        qc = self.classifier
        extract = qc.extract_from_followup_response(user_response, awaiting_slot)
        logger.debug(f"Followup extraction for slot {awaiting_slot}: {extract}")

        if not extract.get("found"):
            return {"status": "slot_not_filled", "details": extract}

        # Update slots
        if awaiting_slot in BIOMARKERS:
            session["slots"].setdefault("biomarkers_detailed", {})
            session["slots"]["biomarkers_detailed"][awaiting_slot] = {
                "value": extract["value"],
                "unit": extract.get("unit", "")
            }
        elif awaiting_slot == "medications":
            session["slots"]["medications"] = extract.get("medications", [])
        else:
            session["slots"][awaiting_slot] = extract.get("value")

        # After updating, re-run the pipeline against last_query_info if available
        last_query = session.get("last_query_info")
        # We don't have the original raw query text reliably; ask caller to re-run handle_user_query if desired.
        return {"status": "slot_filled", "updated_slot": awaiting_slot, "current_slots": session["slots"]}

    # -------------------------
    # Helpers for external callers (UI)
    # -------------------------
    def request_3day_meal_plan(self, session_id: str, accept: bool, foods: Optional[List[Dict[str, Any]]] = None, targets: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Called when user consents to generate a 3-day therapeutic meal plan.
        Foods: optional list of FCT rows provided by front-end. Otherwise use retriever
        Targets: expected structure from ComputationManager (energy/macros, micros)
        """
        session = self._get_session(session_id)

        if not accept:
            return {"status": "declined", "message": "User declined meal plan generation."}

        # Build foods list from retriever if not provided
        if not foods:
            # basic query: fetch common foods for the session country
            country = session["slots"].get("country")
            try:
                docs = filtered_retrieval("common staple foods", {"doc_type": "FCT", "country": country}, k=40)
            except Exception:
                docs = []
            foods_rows = []
            for d in docs or []:
                # Expect metadata includes nutrient fields or FCT rows. Fallback to text.
                meta = getattr(d, "metadata", {})
                row = {
                    "food": meta.get("food") or meta.get("title") or meta.get("chapter_title") or "unknown",
                    "energy": meta.get("energy_kcal", 100),
                    "protein": meta.get("protein_g", 2),
                    "calcium": meta.get("calcium_mg", 0),
                    "iron": meta.get("iron_mg", 0),
                    "zinc": meta.get("zinc_mg", 0),
                    "vitamin_c": meta.get("vitamin_c_mg", 0)
                }
                foods_rows.append(row)
        else:
            foods_rows = foods

        # Build default targets if not provided
        if not targets:
            # try to generate from session slots
            age = int(session["slots"].get("age", 5))
            sex = session["slots"].get("sex", "F")[0].upper()
            weight = session["slots"].get("weight_kg", 15)
            height = session["slots"].get("height_cm", 95)
            targets = self.computation.estimate_energy_macros(age, sex, weight, height, session["slots"].get("activity_level", "light"))

        # Use ComputationManager.optimize_diet_plan (which delegates to nutrient_calculator.optimize_diet)
        plan = self.computation.optimize_diet_plan(foods_rows, {"energy_kcal": targets["calories"]["value"],
                                                                 "macros": {"protein_g": targets["protein"]["value"]},
                                                                 "micros": {}},
                                                   allergies=session["slots"].get("allergies"))
        return {"status": "ok", "meal_plan": plan}

    # -------------------------
    # Backward Compatibility API (for ChatOrchestrator replacement)
    # -------------------------
    def handle_query(self, query: str) -> Dict[str, Any]:
        """
        Backward-compatible wrapper for handle_user_query.
        Uses default session ID for single-session applications.

        This method mimics the old ChatOrchestrator.handle_query() API.
        """
        return self.handle_user_query(self.default_session_id, query)

    def reset_session(self, session_id: Optional[str] = None) -> None:
        """
        Reset session state for the given session_id.
        If no session_id provided, resets the default session.

        This method provides backward compatibility with ChatOrchestrator.reset_session().
        """
        sid = session_id or self.default_session_id
        if sid in self.sessions:
            del self.sessions[sid]
            logger.info(f"Session {sid} reset successfully")
        else:
            logger.warning(f"Attempted to reset non-existent session: {sid}")

    @property
    def session_slots(self) -> Dict[str, Any]:
        """
        Property for backward compatibility with ChatOrchestrator.session_slots.
        Returns the slots dict for the default session.
        """
        session = self._get_session(self.default_session_id)
        return session.get("slots", {})

    # -------------------------
    # Session Management Utilities (from session_manager.py)
    # -------------------------
    def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions.
        Call periodically (e.g., from background task or health check).
        Returns number of sessions cleaned up.
        """
        with self._session_lock:
            now = datetime.utcnow()
            expired = [
                sid for sid, sess in self.sessions.items()
                if now - sess.get("last_accessed", now) > self._session_timeout
            ]
            for sid in expired:
                del self.sessions[sid]
                logger.info(f"Cleaned up expired session {sid}")
            return len(expired)

    def get_session_count(self) -> int:
        """Get total number of active sessions"""
        with self._session_lock:
            return len(self.sessions)

    # -------------------------
    # Slot Validation (from ambiguity_gate.py)
    # -------------------------
    def validate_slots(self, intent: str, slots: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Validate slots against schema.
        Returns (ok, missing_slots, invalid_reasons)
        """
        specs = self.slot_schemas.get(intent, [])
        missing: List[str] = []
        invalid: List[str] = []

        for spec in specs:
            # Check requirement
            if spec.required:
                if spec.name not in slots or slots.get(spec.name) in (None, "", [], {}):
                    missing.append(spec.name)
                    continue

            # Skip validation if slot not present and not required
            if spec.name not in slots:
                continue

            # Enum validation
            if spec.enum and spec.name in slots:
                val = str(slots[spec.name])
                if val not in spec.enum:
                    invalid.append(f"{spec.name} must be one of {spec.enum} (got '{slots[spec.name]}')")

            # Number range validation
            if spec.type == "number" and spec.name in slots:
                try:
                    n = float(slots[spec.name])
                    if spec.min is not None and n < spec.min:
                        invalid.append(f"{spec.name} below minimum {spec.min}")
                    if spec.max is not None and n > spec.max:
                        invalid.append(f"{spec.name} above maximum {spec.max}")
                except Exception:
                    invalid.append(f"{spec.name} must be numeric")

        ok = (len(missing) == 0 and len(invalid) == 0)
        return ok, missing, invalid