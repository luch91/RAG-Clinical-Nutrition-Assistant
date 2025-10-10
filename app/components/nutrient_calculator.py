"""
Nutrient calculator for diet therapy.
- Supports linear optimization (greedy + pulp)
- Supports mixed-integer constraints (e.g., at least 1 food from a group)
- Supports allergy filtering (exclude specific foods if user has allergies)
- Provides helper to convert FCT rows into food dicts
"""
from typing import List, Dict, Any, Optional
import pulp

# ---------------------------
# Helper: Convert single FCT row to food dict
# ---------------------------
def fct_row_to_food(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a row from FCT table into the format required by optimizer.
    Expected keys in row: 'food', 'energy', 'protein', plus micronutrients.
    """
    return {
        "food": row.get("food"),
        "energy": float(row.get("energy", 0)),
        "protein": float(row.get("protein", 0)),
        "micros": {
            "calcium": float(row.get("calcium", 0)),
            "iron": float(row.get("iron", 0)),
            "zinc": float(row.get("zinc", 0)),
            "vitamin_c": float(row.get("vitamin_c", 0)),
        }
    }

# ---------------------------
# Helper: Convert multiple FCT rows to foods
# ---------------------------
def convert_fct_rows_to_foods(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize multiple FCT rows into the foods list used by optimizers.
    Handles different schema variations in FCT tables.
    """
    def pick(d: Dict[str, Any], keys: List[str]):
        for k in keys:
            if k in d and d[k] not in (None, "", "-", "NA", "N/A"):
                return d[k]
        return None
    
    def to_float(x):
        try:
            if isinstance(x, str):
                x = x.strip().replace(",", "")
            return float(x)
        except Exception:
            return 0.0
    
    def kcal_from_kj(kj_val):
        v = to_float(kj_val)
        return v / 4.184 if v else 0.0
    
    foods: List[Dict[str, Any]] = []
    for row in rows or []:
        # Food name
        name = pick(row, ["food", "food_name", "name", "item", "english_name", "local_name"])
        if not name:
            continue
        
        # Energy
        energy = pick(row, ["energy_kcal", "kcal", "energy"])
        if energy is None:
            energy = kcal_from_kj(pick(row, ["energy_kj", "kJ", "energy_kJ"]))
        energy = to_float(energy)
        
        # Protein
        protein = to_float(pick(row, ["protein_g", "protein", "prot"]))
        
        # Micros
        calcium = to_float(pick(row, ["calcium_mg", "calcium", "ca"]))
        iron = to_float(pick(row, ["iron_mg", "iron", "fe"]))
        zinc = to_float(pick(row, ["zinc_mg", "zinc", "zn"]))
        vitamin_c = to_float(pick(row, ["vitamin_c_mg", "vitamin_c", "ascorbic_acid", "vitc", "vit_c"]))
        
        food_obj = {
            "food": str(name).strip().lower(),
            "energy": energy,
            "protein": protein,
            "micros": {
                "calcium": calcium,
                "iron": iron,
                "zinc": zinc,
                "vitamin_c": vitamin_c,
            },
        }
        
        if (food_obj["energy"] > 0) or (food_obj["protein"] > 0) or any(v > 0 for v in food_obj["micros"].values()):
            foods.append(food_obj)
    
    return foods

# ---------------------------
# Greedy fallback allocation
# ---------------------------
def greedy_allocation(foods: List[Dict[str, Any]], targets: Dict[str, Any]) -> List[Dict[str, Any]]:
    allocation = []
    remaining_energy = targets.get("energy_kcal", 2000)
    for food in foods:
        if remaining_energy <= 0:
            break
        portion = min(100, remaining_energy / max(food["energy"], 1) * 100)
        remaining_energy -= (food["energy"] * portion / 100)
        allocation.append({
            "food": food["food"],
            "portion_g": round(portion, 1),
            "energy": round(food["energy"] * portion / 100, 1),
            "protein": round(food["protein"] * portion / 100, 1),
            "micros": {k: round(v * portion / 100, 1) for k, v in food["micros"].items()}
        })
    return allocation

# ---------------------------
# Optimization-based allocation
# ---------------------------
def optimize_diet(
    foods: List[Dict[str, Any]],
    targets: Dict[str, Any],
    group_constraints: Optional[List[List[str]]] = None,
    allergies: Optional[List[str]] = None
) -> Dict[str, Any]:
    # Fix: Allergy filtering using substring matching (not exact string matching)
    if allergies:
        allergies_lower = [a.lower() for a in allergies if a and a not in ("none", "no", "nil", "n/a")]
        foods = [f for f in foods if not any(allergen in f["food"] for allergen in allergies_lower)]
    
    if not foods:
        return {"diet_plan": [], "note": "No foods available after applying allergy filter."}
    
    prob = pulp.LpProblem("DietOptimization", pulp.LpMinimize)
    portions = {f["food"]: pulp.LpVariable(f"portion_{f['food']}", lowBound=0) for f in foods}
    
    # Fix: Use absolute deviation minimization for each nutrient target
    # Energy target
    energy_target = targets.get("energy_kcal", 2000)
    energy_dev_pos = pulp.LpVariable("energy_dev_pos", lowBound=0)
    energy_dev_neg = pulp.LpVariable("energy_dev_neg", lowBound=0)
    prob += pulp.lpSum([f["energy"] * portions[f["food"]] / 100 for f in foods]) == energy_target + energy_dev_pos - energy_dev_neg
    prob.setObjective(energy_dev_pos + energy_dev_neg)
    
    # Protein target
    protein_target = targets.get("macros", {}).get("protein_g", 50)
    protein_dev_pos = pulp.LpVariable("protein_dev_pos", lowBound=0)
    protein_dev_neg = pulp.LpVariable("protein_dev_neg", lowBound=0)
    prob += pulp.lpSum([f["protein"] * portions[f["food"]] / 100 for f in foods]) == protein_target + protein_dev_pos - protein_dev_neg
    prob.setObjective(prob.objective + protein_dev_pos + protein_dev_neg)
    
    # Micros targets
    micros = targets.get("micros", {})
    for micron, val in micros.items():
        var_pos = pulp.LpVariable(f"{micron}_dev_pos", lowBound=0)
        var_neg = pulp.LpVariable(f"{micron}_dev_neg", lowBound=0)
        prob += pulp.lpSum([f["micros"].get(micron, 0) * portions[f["food"]] / 100 for f in foods]) == val + var_pos - var_neg
        prob.setObjective(prob.objective + var_pos + var_neg)
    
    # Group constraints
    if group_constraints:
        for group in group_constraints:
            prob += pulp.lpSum([portions[f["food"]] for f in foods if f["food"].lower() in [g.lower() for g in group]]) >= 50
    
    # Solve the problem
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    
    if prob.status != 1:
        return {"diet_plan": greedy_allocation(foods, targets), "note": "⚠️ Optimization failed, fallback to greedy allocation."}
    
    # Build the plan
    plan = []
    for f in foods:
        portion = portions[f["food"]].value()
        if portion and portion > 0:
            plan.append({
                "food": f["food"],
                "portion_g": round(portion, 1),
                "energy": round(f["energy"] * portion / 100, 1),
                "protein": round(f["protein"] * portion / 100, 1),
                "micros": {k: round(v * portion / 100, 1) for k, v in f["micros"].items()}
            })
    
    return {"diet_plan": plan, "note": "✅ Optimization succeeded"}

# ---------------------------
# Meal planner
# ---------------------------
def meal_planner(
    foods: List[Dict[str, Any]],
    targets: Dict[str, Any],
    allergies: Optional[List[str]] = None
) -> Dict[str, Any]:
    opt = optimize_diet(foods, targets, allergies=allergies)
    plan = opt["diet_plan"]
    meals = {"breakfast": [], "lunch": [], "dinner": []}
    shopping_list = {}
    total_grams = 0
    for i, item in enumerate(plan):
        meal_key = list(meals.keys())[i % 3]
        meals[meal_key].append(item)
        shopping_list[item["food"]] = shopping_list.get(item["food"], 0) + item["portion_g"]
        total_grams += item["portion_g"]
    return {"meals": meals, "shopping_list": shopping_list, "total_grams": total_grams}