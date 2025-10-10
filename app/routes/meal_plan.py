# app/routes/meal_plan.py
from flask import Blueprint, request, jsonify
from app.common.logger import get_logger
from app.components.hybrid_retriever import filtered_retrieval
from app.components.nutrient_calculator import (
    optimize_diet, meal_planner, convert_fct_rows_to_foods
)
from app.components.chat_orchestrator import ChatOrchestrator

bp = Blueprint("meal_plan", __name__)
logger = get_logger(__name__)

def _targets_from_profile(profile):
    sex = str((profile.get("sex") or "male")).lower()
    weight = profile.get("weight_kg")
    # Conservative fallback if unknown weight: adult defaults
    energy_kcal = int(24 * float(weight)) if weight else (2300 if sex == "male" else 2000)
    protein_g = round(1.2 * float(weight), 1) if weight else 60.0
    return {
        "energy_kcal": energy_kcal,
        "macros": {"protein_g": protein_g},
        "micros": {
            "calcium": 1000,
            "iron": 18 if sex == "female" else 8,
            "zinc": 8 if sex == "female" else 11,
            "vitamin_c": 75 if sex == "female" else 90,
        },
        "sources": ["Dietary Reference Intakes", "Clinical Nutrition"],
    }

@bp.route("/api/meal-plan", methods=["POST"])
def generate_meal_plan():
    """
    Body:
      {
        "query": "optional hint like 'staple foods'",
        "profile": { age, sex, weight_kg, height_cm, country, diagnosis, allergies, medications },
        "consent_meal_plan": true,
        "duration_days": 1 or 7
      }
    """
    try:
        data = request.get_json(force=True)
        query = (data.get("query") or "staple foods").strip()
        profile = data.get("profile") or {}
        consent = bool(data.get("consent_meal_plan", False))
        duration_days = int(data.get("duration_days") or 1)

        if not consent:
            return jsonify({"error": "Meal plan generation requires user consent."}), 400

        # We do NOT assume missing data; minimal enforcement: age + sex.
        if not profile.get("age") or not profile.get("sex"):
            return jsonify({
                "error": "Missing required fields for planning.",
                "missing": ["age", "sex"],
                "message": "If weight/height are unknown, we’ll plan using age group (adult/kid) defaults."
            }), 400

        # Build retriever filters
        filters = {}
        if profile.get("country"):
            filters["country_table"] = profile["country"]

        # Pull FCT foods
        retrieved_docs = filtered_retrieval(
            query,
            filters=filters,
            k=14,
            sources=["Food Composition Tables"]
        )
        rows = [doc.metadata for doc in (retrieved_docs or [])]
        foods = convert_fct_rows_to_foods(rows)

        if not foods:
            return jsonify({"error": "No suitable foods found from the FCT."}), 404

        # Targets, allergies & meds
        targets = _targets_from_profile(profile)
        allergies = profile.get("allergies", []) or []
        if isinstance(allergies, str):
            allergies = [allergies]

        # Optimize + plan for ONE DAY first
        try:
            optimized = optimize_diet(foods, targets, allergies=allergies)
        except Exception as e:
            logger.error(f"optimize_diet failed: {e}")
            optimized = {"diet_plan": [], "note": "Optimization failed."}

        try:
            day_plan = meal_planner(foods, targets, allergies=allergies)
        except Exception as e:
            logger.error(f"meal_planner failed: {e}")
            day_plan = {"meals": [], "shopping_list": {}, "total_grams": 0}

        # Compose therapy_output shape
        orchestrator = ChatOrchestrator()
        rationale = orchestrator._biochemical_rationale(profile, targets)
        dni = orchestrator._drug_nutrient_checks(profile.get("medications", [])) if profile.get("medications") else []

        therapy_output = {
            "nutrient_targets": targets,
            "allergies": allergies,
            "optimized_plan": optimized,
            "meals": day_plan.get("meals", []),
            "shopping_list": day_plan.get("shopping_list", {}),
            "total_grams": day_plan.get("total_grams", 0),
            "biochemical_rationale": rationale,
            "drug_nutrient_interactions": dni
        }
        therapy_summary = orchestrator._summarize_therapy_output(profile, therapy_output)

        # Weekly: replicate with simple rotation (placeholder until you add daily variation)
        weekly_plan = []
        if duration_days >= 7:
            base_meals = therapy_output["meals"] or []
            for i in range(7):
                weekly_plan.append({
                    "day": f"Day {i+1}",
                    "meals": base_meals  # could rotate or vary once you extend meal_planner
                })

        # Citations from FCT rows
        citations = []
        for doc in (retrieved_docs or []):
            meta = doc.metadata or {}
            citations.append({
                "food": meta.get("food"),
                "source": meta.get("source") or "Food Composition Tables",
                "ref": meta.get("ref") or meta.get("id") or ""
            })

        return jsonify({
            "therapy_output": therapy_output,
            "therapy_summary": therapy_summary,
            "weekly_plan": weekly_plan if weekly_plan else None,
            "citations": citations,
            "sources": ["Food Composition Tables", "Dietary Reference Intakes", "Clinical Nutrition"],
            "disclaimer": "NutriIntel is for learning and educational purposes only and does not replace professional medical advice."
        })
    except Exception as e:
        logger.error(f"/api/meal-plan failed: {e}")
        return jsonify({"error": "Meal plan generation failed", "detail": str(e)}), 500
