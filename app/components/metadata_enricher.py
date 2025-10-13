"""
Metadata Enrichment for Clinical Chapter Documents

Adds clinical tags to extracted chapters to enable filtered retrieval:
- condition_tags: Clinical conditions covered (e.g., "cystic_fibrosis", "diabetes")
- age_relevance: Age ranges applicable (e.g., "preterm", "0-2y", "3-5y", "6-12y", "13-18y")
- drug_classes: Drug types for drug-nutrient chapters
- therapy_area: One of 8 therapy areas (preterm, t1d, food_allergy, cf, iem, epilepsy, ckd, gi)
"""

from typing import Dict, List, Set
from langchain.schema import Document


# ============================================================================
# DRI (2006) - Dietary Reference Intakes - Section Tags
# ============================================================================

DRI_CONDITION_TAGS = {
    "intro": ["dri_basics", "reference_values", "nutrition_standards"],
    "part1_intro": ["dri_framework", "ear", "rda", "ai", "ul"],
    "part1_apply": ["dri_application", "clinical_use", "assessment", "planning"],
    "part2_intro": ["macronutrients", "physical_activity", "healthful_diets"],
    "energy": ["energy_requirements", "calories", "eer", "tee", "physical_activity_level"],
    "physical_activity": ["exercise", "activity_level", "energy_expenditure"],
    "carbohydrates": ["carbohydrates", "sugars", "starches", "glucose_metabolism"],
    "fiber": ["dietary_fiber", "gut_health", "bowel_function"],
    "fat": ["dietary_fat", "fatty_acids", "essential_fatty_acids", "omega3", "omega6"],
    "cholesterol": ["cholesterol", "cardiovascular_health"],
    "protein": ["protein", "amino_acids", "nitrogen_balance", "protein_quality"],
    "water": ["water", "hydration", "fluid_requirements"],
    # Vitamins
    "vitamin_a": ["vitamin_a", "retinol", "vision", "immune_function"],
    "vitamin_b6": ["vitamin_b6", "pyridoxine", "amino_acid_metabolism"],
    "vitamin_b12": ["vitamin_b12", "cobalamin", "anemia", "neurological_function"],
    "biotin": ["biotin", "b_vitamins", "metabolism"],
    "vitamin_c": ["vitamin_c", "ascorbic_acid", "antioxidant", "iron_absorption"],
    "carotenoids": ["carotenoids", "beta_carotene", "provitamin_a"],
    "choline": ["choline", "brain_development", "liver_function"],
    "vitamin_d": ["vitamin_d", "calcium_absorption", "bone_health", "rickets"],
    "vitamin_e": ["vitamin_e", "tocopherol", "antioxidant"],
    "folate": ["folate", "folic_acid", "neural_tube_defects", "anemia"],
    "vitamin_k": ["vitamin_k", "blood_clotting", "bone_health"],
    "niacin": ["niacin", "b3", "pellagra"],
    "pantothenic_acid": ["pantothenic_acid", "b5", "coenzyme_a"],
    "riboflavin": ["riboflavin", "b2", "energy_metabolism"],
    "thiamin": ["thiamin", "b1", "beriberi", "nervous_system"],
    # Minerals
    "calcium": ["calcium", "bone_health", "teeth", "osteoporosis"],
    "chromium": ["chromium", "glucose_metabolism", "insulin"],
    "copper": ["copper", "iron_metabolism", "connective_tissue"],
    "fluoride": ["fluoride", "dental_health", "tooth_decay"],
    "iodine": ["iodine", "thyroid", "mental_development"],
    "iron": ["iron", "anemia", "hemoglobin", "cognitive_development"],
    "magnesium": ["magnesium", "bone_health", "muscle_function", "nervous_system"],
    "manganese": ["manganese", "bone_formation", "metabolism"],
    "molybdenum": ["molybdenum", "enzyme_function"],
    "phosphorus": ["phosphorus", "bone_health", "energy_metabolism"],
    "potassium": ["potassium", "blood_pressure", "cardiovascular", "electrolyte"],
    "selenium": ["selenium", "antioxidant", "thyroid_function"],
    "sodium_chloride": ["sodium", "chloride", "blood_pressure", "hypertension", "electrolyte"],
    "sulfate": ["sulfate", "sulfur", "protein_structure"],
    "zinc": ["zinc", "immune_function", "growth", "wound_healing"],
    "trace_minerals": ["arsenic", "boron", "nickel", "silicon", "vanadium"],
    # Appendixes
    "appendix_e": ["amino_acids", "indispensable_aa", "iem_requirements", "protein_quality"],
    "appendix_f": ["conversions", "units", "measurement"],
    "appendix_g": ["iron_intake", "population_requirements"],
    "appendix_h": ["ear_statistics", "requirement_variation"],
    "appendix_i": ["intake_variation", "assessment_methodology"],
}

DRI_AGE_RELEVANCE = {
    # All DRI sections apply to all ages (pediatric-specific values included)
    **{section: ["all_ages", "pediatric"] for section in DRI_CONDITION_TAGS.keys()}
}

DRI_THERAPY_AREA = {
    "energy": ["preterm", "cf", "ckd"],
    "protein": ["iem", "preterm", "ckd"],
    "appendix_e": "iem",  # Amino acid requirements critical for PKU/MSUD
    "zinc": ["cf", "gi_disorders"],
    "iron": ["preterm", "ckd"],
    "calcium": ["ckd", "epilepsy"],  # CKD mineral-bone disease, epilepsy AED effects
    "phosphorus": ["ckd"],
    "potassium": ["ckd"],
    "sodium_chloride": ["cf", "ckd"],
    "vitamin_d": ["ckd", "epilepsy"],
    "vitamin_k": ["epilepsy"],  # AED interactions
    "folate": ["epilepsy"],  # AED interactions
    "carbohydrates": ["t1d", "epilepsy"],  # T1D carb counting, ketogenic diet
    "fat": ["cf", "epilepsy"],  # CF fat malabsorption, ketogenic diet
}

# ============================================================================
# SHAW (2020) - Clinical Paediatric Dietetics - Chapter Tags
# ============================================================================

SHAW_CONDITION_TAGS = {
    1: ["general_principles", "pediatric_nutrition_basics"],
    2: ["nutritional_assessment", "anthropometry", "growth_monitoring"],
    3: ["nutrient_requirements", "dietary_reference_values", "macronutrients", "micronutrients"],
    4: ["dietary_counselling", "behavior_change", "feeding_skills"],
    5: ["failure_to_thrive", "faltering_growth", "undernutrition"],
    6: ["nutrition_support", "enteral_feeding", "parenteral_nutrition"],
    7: ["preterm", "nicu", "low_birth_weight", "premature_infant"],
    8: ["gastroenterology", "gi_disorders", "ibd", "crohns", "ulcerative_colitis", "coeliac",
        "gerd", "constipation", "diarrhea", "short_bowel_syndrome"],
    9: ["food_allergy", "cows_milk_allergy", "egg_allergy", "wheat_allergy", "immunology",
        "anaphylaxis", "eosinophilic_disorders"],
    10: ["liver_disease", "hepatology", "cholestatic_liver_disease", "cirrhosis"],
    11: ["diabetes", "type1_diabetes", "t1d", "endocrinology", "obesity", "metabolic_syndrome"],
    12: ["cystic_fibrosis", "cf", "malabsorption", "pancreatic_insufficiency"],
    13: ["kidney_disease", "renal", "ckd", "chronic_kidney_disease", "dialysis", "transplant"],
    14: ["cardiology", "congenital_heart_disease", "chd", "heart_failure"],
    15: ["respiratory", "bronchopulmonary_dysplasia", "bpd", "asthma"],
    16: ["haematology", "oncology", "cancer", "leukaemia", "sickle_cell", "thalassemia"],
    17: ["neurology", "cerebral_palsy", "epilepsy", "neurodisability"],
    18: ["inborn_errors_metabolism", "iem", "pku", "phenylketonuria", "msud", "maple_syrup_urine_disease",
         "galactosemia", "ucd", "urea_cycle_disorders", "organic_acidemias"],
    19: ["ketogenic_diet", "epilepsy", "seizures", "mct_diet", "modified_atkins"],
    20: ["inherited_metabolic_bone_disease", "hypophosphatasia", "osteoporosis"],
    21: ["intensive_care", "picu", "critical_illness", "burns", "trauma"],
    22: ["surgery", "perioperative_nutrition", "postoperative_feeding"],
    23: ["palliative_care", "end_of_life", "symptom_management"],
    24: ["eating_disorders", "anorexia_nervosa", "bulimia", "arfid", "avoidant_restrictive"],
    25: ["mental_health", "adhd", "autism", "asd", "psychiatric_disorders"],
    26: ["vegetarian", "vegan", "plant_based_diet"],
    27: ["sports_nutrition", "adolescent_athlete", "exercise"],
    28: ["complementary_feeding", "weaning", "infant_feeding", "6-12mo"],
    29: ["school_meals", "nutrition_education", "public_health"],
    30: ["cultural_diversity", "religious_diets", "ethnic_foods"],
    31: ["nutritional_products", "formulas", "oral_supplements", "enteral_feeds"]
}

SHAW_AGE_RELEVANCE = {
    1: ["all_ages"],
    2: ["all_ages"],
    3: ["all_ages"],
    4: ["all_ages"],
    5: ["0-2y", "3-5y"],
    6: ["all_ages"],
    7: ["preterm", "0-12mo_corrected"],
    8: ["all_ages"],
    9: ["0-2y", "3-5y", "6-12y", "13-18y"],
    10: ["all_ages"],
    11: ["6-12y", "13-18y"],  # T1D typically school-age+
    12: ["all_ages"],
    13: ["all_ages"],
    14: ["0-2y", "3-5y", "6-12y"],
    15: ["0-2y", "3-5y", "6-12y"],
    16: ["all_ages"],
    17: ["all_ages"],
    18: ["0-2y", "3-5y", "6-12y", "13-18y"],
    19: ["3-5y", "6-12y", "13-18y"],  # Ketogenic typically >2y
    20: ["all_ages"],
    21: ["all_ages"],
    22: ["all_ages"],
    23: ["all_ages"],
    24: ["13-18y"],  # Eating disorders primarily adolescent
    25: ["3-5y", "6-12y", "13-18y"],
    26: ["3-5y", "6-12y", "13-18y"],
    27: ["13-18y"],
    28: ["0-2y"],
    29: ["3-5y", "6-12y", "13-18y"],
    30: ["all_ages"],
    31: ["all_ages"]
}

SHAW_THERAPY_AREA = {
    7: "preterm",
    8: "gi_disorders",
    9: "food_allergy",
    11: "t1d",
    12: "cf",
    13: "ckd",
    17: "epilepsy",
    18: "iem",
    19: "epilepsy"
}


# ============================================================================
# PRETERM NEONATE (2013) - Chapter Tags
# ============================================================================

PRETERM_CONDITION_TAGS = {
    1: ["preterm", "nicu", "prematurity_overview"],
    2: ["nutrient_requirements", "preterm_nutrition_requirements"],
    3: ["feeding_preterm", "enteral_feeding", "parenteral_nutrition", "trophic_feeds"],
    4: ["necrotizing_enterocolitis", "nec", "gut_inflammation"],
    5: ["growth_monitoring", "preterm_growth", "postnatal_growth_restriction"],
    6: ["human_milk", "breast_milk", "fortification", "donor_milk"],
    7: ["preterm_formula", "infant_formula"],
    8: ["parenteral_nutrition", "tpn", "nicu_pn"],
    9: ["lipids", "intravenous_fat", "smof", "intralipid"],
    10: ["amino_acids", "protein", "trophamine"],
    11: ["calcium", "phosphorus", "bone_health", "metabolic_bone_disease"],
    12: ["vitamin_d", "bone_mineralization"],
    13: ["iron", "anemia", "iron_supplementation"],
    14: ["trace_elements", "zinc", "copper", "selenium"],
    15: ["vitamins", "vitamin_a", "vitamin_e", "antioxidants"],
    16: ["probiotics", "gut_microbiome", "nec_prevention"],
    17: ["discharge_planning", "post_nicu", "transitional_feeding"],
    18: ["neurodevelopmental_outcomes", "brain_development", "lcpufa"],
    19: ["bronchopulmonary_dysplasia", "bpd", "chronic_lung_disease"],
    20: ["retinopathy_prematurity", "rop", "eye_development"],
    21: ["family_centered_care", "parent_involvement", "breastfeeding_support"]
}

PRETERM_AGE_RELEVANCE = {
    # All chapters specific to preterm/NICU
    **{i: ["preterm", "0-12mo_corrected"] for i in range(1, 22)}
}

PRETERM_THERAPY_AREA = {
    **{i: "preterm" for i in range(1, 22)}
}


# ============================================================================
# DRUG-NUTRIENT INTERACTIONS (2024) - Chapter Tags
# ============================================================================

DRUG_NUTRIENT_CONDITION_TAGS = {
    1: ["drug_nutrient_interactions_overview", "pharmacology"],
    2: ["drug_absorption", "bioavailability", "pharmacokinetics"],
    3: ["vitamin_b6", "pyridoxine", "drug_interactions"],
    4: ["vitamin_b12", "cobalamin", "metformin", "ppi"],
    5: ["vitamin_c", "ascorbic_acid"],
    6: ["vitamin_d", "calcitriol", "anticonvulsants"],
    7: ["vitamin_e", "tocopherol", "anticoagulants"],
    8: ["vitamin_k", "warfarin", "anticoagulation"],
    9: ["calcium", "calcium_channel_blockers", "bisphosphonates"],
    10: ["magnesium", "diuretics", "ppi"],
    11: ["potassium", "ace_inhibitors", "diuretics"],
    12: ["iron", "antacids", "tetracycline"],
    13: ["zinc", "antibiotics", "penicillamine"],
    14: ["cardiac_drugs", "heart_failure", "digoxin", "ace_inhibitors", "diuretics"],
    15: ["folate", "methotrexate", "anticonvulsants", "sulfasalazine"],
    16: ["antiepileptics", "aed", "phenytoin", "valproate", "carbamazepine"],
    17: ["antimicrobials", "antibiotics", "rifampin", "isoniazid"],
    18: ["antineoplastics", "chemotherapy", "methotrexate"],
    19: ["antipsychotics", "psychiatric_drugs", "weight_gain"],
    20: ["bronchodilators", "theophylline", "asthma_drugs"],
    21: ["corticosteroids", "prednisone", "dexamethasone", "bone_loss"],
    22: ["diabetes_drugs", "insulin", "metformin", "sulfonylureas"],
    23: ["gi_drugs", "ppi", "h2_blockers", "laxatives"],
    24: ["immunosuppressants", "cyclosporine", "tacrolimus", "transplant_drugs"],
    25: ["nsaids", "pain_medications", "aspirin", "ibuprofen"],
    26: ["herbal_supplements", "drug_herb_interactions", "st_johns_wort"]
}

DRUG_NUTRIENT_DRUG_CLASSES = {
    3: ["isoniazid", "levodopa", "penicillamine"],
    4: ["metformin", "ppi", "h2_blockers", "colchicine"],
    5: ["aspirin", "oral_contraceptives", "corticosteroids"],
    6: ["anticonvulsants", "corticosteroids", "rifampin"],
    7: ["warfarin", "aspirin", "cholesterol_lowering_drugs"],
    8: ["warfarin", "antibiotics", "anticonvulsants"],
    9: ["calcium_channel_blockers", "loop_diuretics", "corticosteroids", "bisphosphonates"],
    10: ["loop_diuretics", "thiazide_diuretics", "ppi", "amphotericin"],
    11: ["ace_inhibitors", "arbs", "potassium_sparing_diuretics", "nsaids"],
    12: ["antacids", "ppi", "tetracycline", "fluoroquinolones"],
    13: ["penicillamine", "quinolones", "tetracycline"],
    14: ["digoxin", "ace_inhibitors", "arbs", "beta_blockers", "loop_diuretics"],
    15: ["methotrexate", "phenytoin", "phenobarbital", "sulfasalazine", "trimethoprim"],
    16: ["phenytoin", "phenobarbital", "carbamazepine", "valproate", "lamotrigine"],
    17: ["rifampin", "isoniazid", "tetracycline", "fluoroquinolones"],
    18: ["methotrexate", "cisplatin", "ifosfamide"],
    19: ["chlorpromazine", "haloperidol", "olanzapine", "risperidone"],
    20: ["theophylline", "albuterol", "corticosteroids"],
    21: ["prednisone", "dexamethasone", "hydrocortisone"],
    22: ["insulin", "metformin", "sulfonylureas", "sglt2_inhibitors"],
    23: ["ppi", "h2_blockers", "laxatives", "antacids"],
    24: ["cyclosporine", "tacrolimus", "sirolimus", "mycophenolate"],
    25: ["aspirin", "ibuprofen", "naproxen", "celecoxib"],
    26: ["st_johns_wort", "ginkgo", "ginseng", "echinacea"]
}

DRUG_NUTRIENT_THERAPY_AREA = {
    14: "ckd",  # Cardiac drugs overlap with CKD
    15: ["iem", "epilepsy"],  # Folate - both IEM and epilepsy
    16: "epilepsy",
    17: ["cf", "gi_disorders"],  # Antimicrobials common in CF
    18: [],  # Chemotherapy not primary pediatric therapy area
    21: ["cf", "gi_disorders", "ckd"],  # Corticosteroids used in multiple
    22: "t1d",
    23: "gi_disorders",
    24: [],  # Immunosuppressants (transplant) not primary therapy area
}

DRUG_NUTRIENT_AGE_RELEVANCE = {
    **{i: ["all_ages"] for i in range(1, 27)}
}


# ============================================================================
# INTEGRATIVE HUMAN BIOCHEMISTRY (2022) - Section Tags
# ============================================================================

BIOCHEM_CONDITION_TAGS = {
    "1.1": ["carbohydrate_structure", "monosaccharides", "polysaccharides"],
    "1.2": ["glycolysis", "glucose_metabolism"],
    "1.3": ["gluconeogenesis", "glucose_synthesis"],
    "1.4": ["glycogen_metabolism", "glycogenolysis", "glycogen_storage"],
    "1.5": ["pentose_phosphate_pathway", "nadph", "ribose"],
    "1.6": ["fructose_metabolism", "galactose_metabolism"],

    "2.1": ["citric_acid_cycle", "tca_cycle", "krebs_cycle"],
    "2.2": ["electron_transport_chain", "oxidative_phosphorylation", "atp_synthesis"],
    "2.3": ["mitochondrial_disorders"],

    "3.1": ["amino_acid_structure", "protein_structure"],
    "3.2": ["protein_digestion", "amino_acid_absorption"],
    "3.3": ["amino_acid_metabolism", "transamination", "deamination"],
    "3.4": ["urea_cycle", "ammonia_detoxification", "ucd"],
    "3.5": ["amino_acid_disorders", "pku", "msud", "homocystinuria"],
    "3.6": ["protein_synthesis", "translation"],

    "4.1": ["purine_metabolism", "nucleotide_synthesis"],
    "4.2": ["pyrimidine_metabolism"],
    "4.3": ["nucleotide_disorders", "gout", "lesch_nyhan"],

    "5.1": ["lipid_structure", "fatty_acids", "triglycerides"],
    "5.2": ["lipid_digestion", "fat_absorption", "chylomicrons"],
    "5.3": ["lipoprotein_metabolism", "cholesterol", "ldl", "hdl"],
    "5.4": ["fatty_acid_synthesis", "lipogenesis"],
    "5.5": ["fatty_acid_oxidation", "beta_oxidation"],
    "5.6": ["ketone_body_metabolism", "ketogenesis", "ketolysis"],
    "5.7": ["cholesterol_synthesis", "steroid_hormones"],
    "5.8": ["lipid_disorders", "hyperlipidemia", "fatty_acid_oxidation_disorders"],

    "6.1": ["hormone_overview", "endocrine_system"],
    "6.2": ["insulin", "glucagon", "blood_glucose_regulation"],
    "6.3": ["thyroid_hormones", "t3", "t4"],
    "6.4": ["growth_hormone", "igf1"],
    "6.5": ["cortisol", "stress_hormones"],

    "7.1": ["vitamin_overview"],
    "7.2": ["fat_soluble_vitamins", "vitamin_a", "vitamin_d", "vitamin_e", "vitamin_k"],
    "7.3": ["water_soluble_vitamins", "b_vitamins", "vitamin_c"],
    "7.4": ["vitamin_deficiency", "scurvy", "beriberi", "pellagra"],

    "8.1": ["mineral_overview", "electrolytes"],
    "8.2": ["calcium_metabolism", "phosphorus", "bone_health"],
    "8.3": ["iron_metabolism", "heme_synthesis"],
    "8.4": ["trace_minerals", "zinc", "copper", "selenium"],

    "9.1": ["dna_structure", "replication"],
    "9.2": ["rna_transcription", "gene_expression"],
    "9.3": ["genetic_mutations", "inherited_disorders"],

    "10.1": ["metabolic_integration", "fed_state"],
    "10.2": ["fasting_state", "starvation"],
    "10.3": ["exercise_metabolism"],

    "11.1": ["diabetes_mellitus", "hyperglycemia", "t1d", "t2d"],
    "11.2": ["metabolic_acidosis", "ketoacidosis", "dka"],
    "11.3": ["metabolic_alkalosis"],
}

# Map biochemistry sections to therapy areas
BIOCHEM_THERAPY_AREA = {
    "1.4": "iem",  # Glycogen storage diseases
    "1.6": "iem",  # Fructose/galactose disorders
    "2.3": "iem",  # Mitochondrial disorders
    "3.4": "iem",  # Urea cycle disorders
    "3.5": "iem",  # Amino acid disorders (PKU, MSUD)
    "5.6": "epilepsy",  # Ketone body metabolism (ketogenic diet)
    "5.8": "iem",  # Fatty acid oxidation disorders
    "6.2": "t1d",  # Insulin/glucagon
    "11.1": "t1d",  # Diabetes mellitus
    "11.2": "t1d",  # Ketoacidosis
}

BIOCHEM_AGE_RELEVANCE = {
    **{section: ["all_ages"] for section in BIOCHEM_CONDITION_TAGS.keys()}
}


# ============================================================================
# MAIN ENRICHMENT FUNCTION
# ============================================================================

def enrich_chapter_metadata(doc: Document, doc_type: str) -> Document:
    """
    Add clinical tags to chapter metadata for filtered retrieval.

    Args:
        doc: Document object from chapter_extractor.py
        doc_type: One of "dri", "shaw_2020", "preterm_2013", "drug_nutrient", "biochemistry"

    Returns:
        Document with enriched metadata
    """
    chapter_num = doc.metadata.get("chapter_num")
    section_num = doc.metadata.get("section_num")

    # Default empty tags
    condition_tags: List[str] = []
    age_relevance: List[str] = []
    drug_classes: List[str] = []
    therapy_area: List[str] = []

    if doc_type == "dri":
        # DRI uses string keys like "vitamin_a" for chapter_num
        condition_tags = DRI_CONDITION_TAGS.get(chapter_num, [])
        age_relevance = DRI_AGE_RELEVANCE.get(chapter_num, [])
        therapy = DRI_THERAPY_AREA.get(chapter_num)
        if therapy:
            if isinstance(therapy, list):
                therapy_area = therapy
            else:
                therapy_area = [therapy]

    elif doc_type == "shaw_2020":
        condition_tags = SHAW_CONDITION_TAGS.get(chapter_num, [])
        age_relevance = SHAW_AGE_RELEVANCE.get(chapter_num, [])
        therapy = SHAW_THERAPY_AREA.get(chapter_num)
        if therapy:
            therapy_area = [therapy]

    elif doc_type == "preterm_2013":
        condition_tags = PRETERM_CONDITION_TAGS.get(chapter_num, [])
        age_relevance = PRETERM_AGE_RELEVANCE.get(chapter_num, [])
        therapy = PRETERM_THERAPY_AREA.get(chapter_num)
        if therapy:
            therapy_area = [therapy]

    elif doc_type == "drug_nutrient":
        condition_tags = DRUG_NUTRIENT_CONDITION_TAGS.get(chapter_num, [])
        age_relevance = DRUG_NUTRIENT_AGE_RELEVANCE.get(chapter_num, [])
        drug_classes = DRUG_NUTRIENT_DRUG_CLASSES.get(chapter_num, [])
        therapy = DRUG_NUTRIENT_THERAPY_AREA.get(chapter_num)
        if therapy:
            if isinstance(therapy, list):
                therapy_area = therapy
            else:
                therapy_area = [therapy]

    elif doc_type == "biochemistry":
        condition_tags = BIOCHEM_CONDITION_TAGS.get(section_num, [])
        age_relevance = BIOCHEM_AGE_RELEVANCE.get(section_num, [])
        therapy = BIOCHEM_THERAPY_AREA.get(section_num)
        if therapy:
            therapy_area = [therapy]

    # Add enriched metadata
    doc.metadata["condition_tags"] = condition_tags
    doc.metadata["age_relevance"] = age_relevance
    doc.metadata["drug_classes"] = drug_classes
    doc.metadata["therapy_area"] = therapy_area

    return doc


def enrich_documents(documents: List[Document], doc_type: str) -> List[Document]:
    """
    Enrich all documents from a single source.

    Args:
        documents: List of Document objects from chapter_extractor
        doc_type: One of "dri", "shaw_2020", "preterm_2013", "drug_nutrient", "biochemistry"

    Returns:
        List of enriched Document objects
    """
    enriched_docs = []
    for doc in documents:
        enriched_doc = enrich_chapter_metadata(doc, doc_type)
        enriched_docs.append(enriched_doc)

    return enriched_docs


# ============================================================================
# QUERY HELPER FUNCTIONS
# ============================================================================

def get_relevant_chapters_for_condition(condition: str, doc_type: str = "shaw_2020") -> List[int]:
    """
    Get chapter numbers relevant to a clinical condition.

    Args:
        condition: Clinical condition (e.g., "cystic_fibrosis", "t1d")
        doc_type: Document type to search

    Returns:
        List of chapter numbers containing the condition
    """
    condition = condition.lower()
    relevant_chapters = []

    if doc_type == "dri":
        tag_map = DRI_CONDITION_TAGS
    elif doc_type == "shaw_2020":
        tag_map = SHAW_CONDITION_TAGS
    elif doc_type == "preterm_2013":
        tag_map = PRETERM_CONDITION_TAGS
    elif doc_type == "drug_nutrient":
        tag_map = DRUG_NUTRIENT_CONDITION_TAGS
    elif doc_type == "biochemistry":
        tag_map = BIOCHEM_CONDITION_TAGS
    else:
        return []

    for chapter_num, tags in tag_map.items():
        if any(condition in tag for tag in tags):
            relevant_chapters.append(chapter_num)

    return relevant_chapters


def get_drug_interaction_chapters(medication: str) -> List[int]:
    """
    Get drug-nutrient interaction chapter numbers for a medication.

    Args:
        medication: Medication name (e.g., "phenytoin", "metformin")

    Returns:
        List of chapter numbers from Drug-Nutrient handbook
    """
    medication = medication.lower()
    relevant_chapters = []

    for chapter_num, drug_classes in DRUG_NUTRIENT_DRUG_CLASSES.items():
        if any(medication in drug_class for drug_class in drug_classes):
            relevant_chapters.append(chapter_num)

    return relevant_chapters
