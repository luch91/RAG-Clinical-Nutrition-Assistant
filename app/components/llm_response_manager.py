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
"""
from typing import Dict, Any, List, Optional, Tuple
import logging
import math

from app.components.query_classifier import NutritionQueryClassifier
from app.components.followup_question_generator import FollowUpQuestionGenerator
from app.components.hybrid_retriever import filtered_retrieval, retriever
from app.components.computation_manager import ComputationManager

logger = logging.getLogger(__name__)

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
    def _init_(self, dri_table_path: str = "data/dri_table.csv"):
        # Core components
        self.classifier = NutritionQueryClassifier()
        self.followup_gen = FollowUpQuestionGenerator()
        self.computation = ComputationManager(dri_table_path)

        # Per-session state (simple dict). Keys: slots, profile, clarifications, conversation metadata
        self.sessions: Dict[str, Dict[str, Any]] = {}

    # -------------------------
    # Session helpers
    # -------------------------
    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            # initialize
            self.sessions[session_id] = {
                "slots": {},            # age, sex, weight_kg, height_cm, diagnosis, medications, biomarkers, country, allergies, etc.
                "lab_results": [],      # parsed labs (if user uploaded)
                "last_query_info": None,
                "clarifications": {},   # e.g., {"mode":"step_by_step"}
            }
        return self.sessions[session_id]

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
        Returns a small dict of extracted entities.
        """
        ent = {
            "diagnosis": self.classifier._extract_diagnosis(query),
            "biomarkers_detailed": self.classifier.extract_biomarkers_with_values(query),
            "biomarkers": self.classifier.extract_biomarkers(query),
            "medications": self.classifier.extract_medications(query),
            "country": self.classifier._extract_country(query),
        }
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
        """
        session = self._get_session(session_id)

        # 1) classify
        query_info = self.classify_query(session_id, user_query)
        label = query_info.get("label", "general")
        session["last_query_info"] = query_info

        # 2) extract entities and merge into session slots if present
        entities = self.extract_entities(user_query)
        # merge: prefer existing slots; update if new info extracted
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
            return {"status": "needs_slot", "followup": followup}

        # Now ensure required clinical slots are present: medications, biomarkers (or lab_results), age/anthro, country
        followup = self.followup_gen.generate_follow_up_question(query_info, session.get("slots"), session.get("lab_results"), session.get("clarifications"))
        if followup:
            return {"status": "needs_slot", "followup": followup}

        # All required slots present -> compute therapeutic targets
        slots = session["slots"]
        age = int(slots.get("age")) if slots.get("age") is not None else None
        sex = slots.get("sex", "F")[0].upper()
        weight = slots.get("weight_kg")
        height = slots.get("height_cm")
        meds = slots.get("medications", [])
        biomarkers = session.get("lab_results") or slots.get("biomarkers_detailed", {})

        # 1) compute macros & energy
        energy_macros = self.computation.estimate_energy_macros(age, sex, weight, height, slots.get("activity_level", "light"))

        # 2) retrieve therapeutic nutrient guidance: prefer chapter-aware retrieval for condition
        # Build retrieval filters: therapy_area based on diagnosis
        therapy_area = None
        for k,v in SUPPORTED_THERAPY_CONDITIONS.items():
            if k in diagnosis.lower():
                therapy_area = v
                break

        # Query clinical texts for therapeutic nutrient constraints for this therapy_area
        filter_candidates = [{"therapy_area": therapy_area}, {"doc_type": "shaw_2020"}, {"doc_type": "dri"}]
        clinical_docs = []
        for f in filter_candidates:
            try:
                docs = filtered_retrieval(f"therapeutic {diagnosis} nutrition", f, k=5)
            except Exception:
                docs = []
            if docs:
                clinical_docs = docs
                break

        # 3) For each key nutrient relevant to the condition, fetch matching foods from FCT
        # We'll decide a short list of condition-relevant nutrients via metadata_enricher mapping if present in docs.
        condition_nutrients = ["protein", "energy", "fat", "carbohydrate", "sodium", "potassium", "calcium", "iron"]
        food_matches = {}
        for nut in condition_nutrients:
            try:
                docs = filtered_retrieval(f"food sources of {nut}", {"doc_type": "FCT", "country": slots.get("country")}, k=6)
            except Exception:
                docs = []
            food_matches[nut] = [{"title": getattr(d, "metadata", {}).get("food") or getattr(d, "metadata", {}).get("chapter_title",""),
                                   "snippet": (d.page_content[:200] if getattr(d, "page_content", None) else "")} for d in docs or []]

        payload = {
            "status": "therapy_ready",
            "diagnosis": diagnosis.title() if diagnosis else None,
            "therapy_area": therapy_area,
            "energy_macros": energy_macros,
            "clinical_docs_count": len(clinical_docs),
            "food_matches": food_matches,
            "message": "Therapeutic targets and food sources prepared. Offer: generate 3-day therapeutic meal plan?"
        }
        # Attach clinical snippets if available
        payload["clinical_snippets"] = []
        for d in clinical_docs[:3]:
            payload["clinical_snippets"].append({
                "title": getattr(d, "metadata", {}).get("chapter_title", ""),
                "source": getattr(d, "metadata", {}).get("book_title", ""),
                "snippet": (d.page_content[:300] if getattr(d, "page_content", None) else "")
            })

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
        session = self._get_session(session_id)
        qc = self.classifier
        extract = qc.extract_from_followup_response(user_response, awaiting_slot)
        logger.debug(f"Followup extraction for slot {awaiting_slot}: {extract}")

        if not extract.get("found"):
            return {"status": "slot_not_filled", "details": extract}

        # Update slots
        if awaiting_slot in qc.BIOMARKERS:
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