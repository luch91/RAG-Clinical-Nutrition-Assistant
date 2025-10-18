"""
Fixed _get_biomarker_questions method - reordered to prevent PKU matching epilepsy
"""
def _get_biomarker_questions_FIXED(diagnosis: str):
    """Get diagnosis-specific biomarker questions for ALL 8 supported conditions"""
    questions = []

    diagnosis_lower = (diagnosis or "").lower()

    # 1. Type 1 Diabetes
    if "diabet" in diagnosis_lower or "t1d" in diagnosis_lower or "iddm" in diagnosis_lower:
        questions.extend([
            {"slot": "hba1c"},
            {"slot": "glucose"}
        ])

    # 2. Chronic Kidney Disease (CKD)
    elif "ckd" in diagnosis_lower or "kidney" in diagnosis_lower or "renal" in diagnosis_lower:
        questions.extend([
            {"slot": "creatinine"},
            {"slot": "egfr"},
            {"slot": "potassium"},
            {"slot": "phosphorus"}
        ])

    # 3. Inherited Metabolic Disorders (PKU, MSUD, Galactosemia) - CHECK BEFORE EPILEPSY
    # CRITICAL: Must be before epilepsy check because "keto" in epilepsy matches "phenylKETOnuria"
    elif any(term in diagnosis_lower for term in ["pku", "phenylketonuria", "msud", "maple syrup", "galactosemia", "metabolic disorder", "inborn error"]):
        # PKU-specific
        if "pku" in diagnosis_lower or "phenylketonuria" in diagnosis_lower:
            questions.extend([
                {"slot": "phenylalanine"},
                {"slot": "tyrosine"}
            ])

        # MSUD-specific
        elif "msud" in diagnosis_lower or "maple syrup" in diagnosis_lower:
            questions.extend([
                {"slot": "leucine"},
                {"slot": "isoleucine"},
                {"slot": "valine"}
            ])

        # Galactosemia-specific
        elif "galactosemia" in diagnosis_lower:
            questions.extend([
                {"slot": "galactose_1_phosphate"},
                {"slot": "galt_activity"}
            ])

        # General metabolic markers (for all IEMs)
        questions.append({"slot": "albumin"})

    # 4. Epilepsy / Ketogenic Therapy - AFTER metabolic disorders
    elif "epilep" in diagnosis_lower or "seizure" in diagnosis_lower or "ketogenic" in diagnosis_lower or "keto" in diagnosis_lower:
        questions.extend([
            {"slot": "aed_level"},
            {"slot": "ketone_level"},
            {"slot": "seizure_frequency"}
        ])

    # 5. Cystic Fibrosis (CF)
    elif "cystic fibrosis" in diagnosis_lower or ("cf" in diagnosis_lower and len(diagnosis_lower) <= 5) or "cftr" in diagnosis_lower:
        questions.extend([
            {"slot": "fev1"},
            {"slot": "pancreatic_status"},
            {"slot": "vitamin_d"},
            {"slot": "vitamin_a"}
        ])

    # 6. Preterm Nutrition
    elif "preterm" in diagnosis_lower or "premature" in diagnosis_lower or "nicu" in diagnosis_lower or "preemie" in diagnosis_lower:
        questions.extend([
            {"slot": "gestational_age"},
            {"slot": "corrected_age"},
            {"slot": "feeding_method"},
            {"slot": "hemoglobin"}
        ])

    # 7. Food Allergy
    elif "food allerg" in diagnosis_lower or ("allergic" in diagnosis_lower and "food" not in diagnosis_lower) or "anaphylaxis" in diagnosis_lower:
        questions.extend([
            {"slot": "allergen_type"},
            {"slot": "ige_level"},
            {"slot": "reaction_severity"}
        ])

    # 8. GI Disorders (IBD, GERD, Crohn's, Ulcerative Colitis)
    elif any(term in diagnosis_lower for term in ["ibd", "crohn", "ulcerative colitis", "gerd", "reflux", "inflammatory bowel"]):
        # IBD-specific (Crohn's, UC)
        if any(term in diagnosis_lower for term in ["ibd", "crohn", "ulcerative colitis", "inflammatory bowel"]):
            questions.extend([
                {"slot": "crp"},
                {"slot": "esr"},
                {"slot": "fecal_calprotectin"},
                {"slot": "albumin"}
            ])

        # GERD-specific
        if "gerd" in diagnosis_lower or "reflux" in diagnosis_lower:
            questions.append({"slot": "symptom_frequency"})

    return [q["slot"] for q in questions]


# Test the ordering logic
if __name__ == "__main__":
    test_cases = [
        ("Phenylketonuria", ["phenylalanine", "tyrosine", "albumin"]),
        ("PKU", ["phenylalanine", "tyrosine", "albumin"]),
        ("Epilepsy", ["aed_level", "ketone_level", "seizure_frequency"]),
        ("Ketogenic diet", ["aed_level", "ketone_level", "seizure_frequency"]),
    ]

    print("Testing ordering fix:")
    for diagnosis, expected in test_cases:
        result = _get_biomarker_questions_FIXED(diagnosis)
        match = result == expected
        print(f"{diagnosis:30s} : {'PASS' if match else 'FAIL'} -> {result}")
