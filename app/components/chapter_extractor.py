# app/components/chapter_extractor.py
"""
Chapter-aware PDF extraction using table of contents structure.
Extracts clinical textbook chapters as semantic units for intelligent retrieval.
"""
import os
import re
from typing import List, Dict, Any, Tuple
from langchain.docstore.document import Document
from langchain_community.document_loaders import PyPDFLoader
from app.common.logger import get_logger

logger = get_logger(__name__)

# ==============================================================================
# TABLE OF CONTENTS DEFINITIONS
# ==============================================================================

# Shaw (2020) - Clinical Paediatric Dietetics
SHAW_TOC = {
    1: {"title": "Principles of Paediatric Dietetics", "pages": (1, 17), "authors": ["Vanessa Shaw", "Helen McCarthy"]},
    2: {"title": "Healthy Eating", "pages": (18, 42), "authors": ["Judy More"]},
    3: {"title": "Provision of Nutrition in a Hospital Setting", "pages": (43, 51), "authors": ["Julie Royle"]},
    4: {"title": "Enteral Nutrition", "pages": (52, 63), "authors": ["Tracey Johnson"]},
    5: {"title": "Parenteral Nutrition", "pages": (64, 79), "authors": ["Joanne Louise Price"]},
    6: {"title": "Nutrition in Critically Ill Children", "pages": (80, 95), "authors": ["Rosan Meyer", "Luise Marino"]},
    7: {"title": "Preterm Infants", "pages": (96, 112), "authors": ["Karen King", "Lynne Radbone"]},
    8: {"title": "Gastroenterology", "pages": (113, 148), "authors": ["Sarah Macdonald", "Joanne Louise Price"]},
    9: {"title": "Surgery in the Gastrointestinal Tract", "pages": (149, 165), "authors": ["Danielle Petersen", "Tracey Johnson"]},
    10: {"title": "The Liver and Pancreas", "pages": (166, 188), "authors": ["Sara Mancell"]},
    11: {"title": "Endocrinology", "pages": (189, 215), "authors": ["S. Francesca Annan", "Sarah Price"]},
    12: {"title": "Cystic Fibrosis", "pages": (216, 237), "authors": ["Carolyn Patchell", "Katie Stead"]},
    13: {"title": "Kidney Diseases", "pages": (238, 286), "authors": ["Leila Qizalbash", "Shelley Cleghorn", "Louise McAlister"]},
    14: {"title": "Congenital Heart Disease", "pages": (287, 314), "authors": ["David Hopkins", "Luise Marino"]},
    15: {"title": "Food Hypersensitivity", "pages": (315, 338), "authors": ["Rosan Meyer", "Carina Venter"]},
    16: {"title": "Prevention of Food Allergy", "pages": (339, 343), "authors": ["Kate Grimshaw"]},
    17: {"title": "Ketogenic Diets", "pages": (344, 370), "authors": ["Julia Ackrill", "Vanessa Appleyard", "Victoria Whiteley"]},
    18: {"title": "Childhood Cancers and Immunodeficiency Syndromes", "pages": (371, 392), "authors": ["Evelyn Ward", "James Evans"]},
    19: {"title": "Eating Disorders", "pages": (393, 404), "authors": ["Graeme O'Connor", "Dasha Nicholls"]},
    20: {"title": "Autism", "pages": (405, 418), "authors": ["Zoe Connor"]},
    21: {"title": "Feeding Children with Neurodisabilities", "pages": (419, 437), "authors": ["Jennifer Douglas"]},
    22: {"title": "Epidermolysis Bullosa and Rare Skin Disorders", "pages": (438, 455), "authors": ["Natalie Yerlett"]},
    23: {"title": "Burns", "pages": (456, 463), "authors": ["Helen McCarthy", "Jacqueline Lowdon"]},
    24: {"title": "Faltering Weight", "pages": (464, 471), "authors": ["Lisa Cooke", "Julie Lanigan"]},
    25: {"title": "Obesity in Childhood", "pages": (472, 485), "authors": ["Laura Stewart", "Chris Smith"]},
    26: {"title": "Eating for Children from Minority Ethnic Groups", "pages": (486, 501), "authors": ["Eulalee Green"]},
    27: {"title": "Inherited Metabolic Disorders: Introduction and Rare Disorders", "pages": (502, 512), "authors": ["Fiona J. White"]},
    28: {"title": "Disorders of Amino Acid Metabolism, Organic Acidaemias and Urea Cycle Disorders", "pages": (513, 598), "authors": ["Marjorie Dixon", "Anita MacDonald", "Fiona J. White"]},
    29: {"title": "Disorders of Carbohydrate Metabolism", "pages": (599, 639), "authors": ["Anita MacDonald", "Marjorie Dixon", "Fiona J. White"]},
    30: {"title": "Disorders of Mitochondrial Fatty Acid Oxidation and Lipid Metabolism", "pages": (640, 672), "authors": ["Marjorie Dixon", "Rachel Skeath", "Fiona J. White"]},
    31: {"title": "Emergency Regimens for Inherited Metabolic Disorders", "pages": (673, 700), "authors": ["Marjorie Dixon"]},
}

# Preterm Neonate (2013) - Nutrition for the Preterm Neonate
PRETERM_TOC = {
    1: {"title": "Developmental Physiology of the Gastrointestinal Tract and Feed Intolerance", "pages": (3, 26), "authors": ["Sanjay Patole"]},
    2: {"title": "Minimal Enteral Feeding", "pages": (27, 46), "authors": ["Olachi Mezu-Ndubuisi", "Akhil Maheshwari"]},
    3: {"title": "Strategies for Managing Feed Intolerance in Preterm Neonates", "pages": (47, 70), "authors": ["Sanjay Patole"]},
    4: {"title": "Prevention and Treatment of Necrotising Enterocolitis in Preterm Neonates", "pages": (71, 96), "authors": ["Sanjay Patole"]},
    5: {"title": "Aggressive Enteral Nutrition in Preterm Neonates", "pages": (97, 114), "authors": ["Sanjay Patole"]},
    6: {"title": "Metabolic Bone Disease of Prematurity", "pages": (115, 134), "authors": ["Suresh Birajdar", "Mary Sharp", "Sanjay Patole"]},
    7: {"title": "Gastro-Esophageal Reflux in Neonatology", "pages": (135, 152), "authors": ["Keith J. Barrington"]},
    8: {"title": "Breast Milk Additives and Infant Formula", "pages": (153, 172), "authors": ["Jill Sherriff", "Gemma McLeod"]},
    9: {"title": "Post-Discharge Nutrition for High-Risk Preterm Neonates", "pages": (173, 192), "authors": ["Gemma McLeod", "Jill Sherriff", "Sanjay Patole"]},
    10: {"title": "The History, Principles, and Practice of Parenteral Nutrition in Preterm Neonates", "pages": (193, 214), "authors": ["Stanley J. Dudrick", "Alpin D. Malkan"]},
    11: {"title": "Intravenous Lipids in Neonates", "pages": (215, 232), "authors": ["Girish Deshpande", "Rajesh Maheshwari"]},
    12: {"title": "Amino Acids", "pages": (233, 252), "authors": ["Hester Vlaardingerbroek", "Johannes B. van Goudoever"]},
    13: {"title": "Aggressive Parenteral Nutrition", "pages": (253, 268), "authors": ["Karen Simmer"]},
    14: {"title": "Catch up Growth and the Developmental Origins of Health and Disease (DOHaD)", "pages": (269, 292), "authors": ["Nicholas D. Embleton", "Claire L. Wood", "Robert J. Tinnion"]},
    15: {"title": "Growth Monitoring of Preterm Infants", "pages": (293, 310), "authors": ["Shripada Rao"]},
    16: {"title": "Role of Breast Milk", "pages": (311, 336), "authors": ["Jacqueline C. Kent", "Lukas Christen", "Foteini Hassiotou", "Peter E. Hartmann"]},
    17: {"title": "Breastfeeding the Preterm Infant", "pages": (337, 366), "authors": ["Perrella Sharon", "Boss Melinda", "Geddes Donna"]},
    18: {"title": "Donor Human Milk Banking in Neonatal Intensive Care", "pages": (367, 390), "authors": ["Ben T Hartmann", "Lukas Christen"]},
    19: {"title": "Feeding the Preterm Neonate with Intra Uterine Growth Restriction", "pages": (391, 404), "authors": ["Flavia Indrio", "Luca Maggio", "Francesco Raimondi"]},
    20: {"title": "Nutrition in Intestinal Failure/Short Bowel Syndrome", "pages": (405, 420), "authors": ["Jatinder Bhatia", "Cynthia Mundy"]},
    21: {"title": "Nutrition in Preterm Infants with Bronchopulmonary Dysplasia", "pages": (421, 440), "authors": ["Noa Ofek Shlomai", "Sanjay Patole"]},
}

# Drug-Nutrient Handbook (2024)
DRUG_NUTRIENT_TOC = {
    1: {"title": "A Perspective on Drug-Nutrient Interactions", "pages": (3, 26), "authors": ["Joseph I. Boullata", "Jacqueline R. Barber"]},
    2: {"title": "Drug Disposition and Response", "pages": (27, 42), "authors": ["Robert B. Raffa"]},
    3: {"title": "Drug-Metabolizing Enzymes and P-Glycoprotein", "pages": (43, 68), "authors": ["Thomas K. H. Chang"]},
    4: {"title": "Nutrient Disposition and Response", "pages": (69, 82), "authors": ["Francis E. Rosato Jr."]},
    5: {"title": "The Impact of Protein-Calorie Malnutrition on Drugs", "pages": (83, 100), "authors": ["Charlene W. Compher"]},
    6: {"title": "Influence of Obesity on Drug Disposition and Effect", "pages": (101, 128), "authors": ["Joseph I. Boullata"]},
    7: {"title": "Drug Absorption With Food", "pages": (129, 154), "authors": ["David Fleisher", "Burgunda V. Sweet", "Ameeta Parekh"]},
    8: {"title": "Effects of Specific Foods and Non-Nutritive Dietary Components on Drug Metabolism", "pages": (155, 174), "authors": ["Karl E. Anderson"]},
    9: {"title": "Grapefruit Juice-Drug Interaction Issues", "pages": (175, 194), "authors": ["David G. Bailey"]},
    10: {"title": "Nutrients That May Optimize Drug Effects", "pages": (195, 216), "authors": ["Imad F. Btaiche", "Michael D. Kraft"]},
    11: {"title": "Dietary Supplement Interactions With Medication", "pages": (217, 234), "authors": ["Jeffrey J. Mucksavage", "Lingtak-Neander Chan"]},
    12: {"title": "Dietary Supplement Interaction With Nutrients", "pages": (235, 242), "authors": ["Mariana Markell"]},
    13: {"title": "Drug-Induced Changes to Nutritional Status", "pages": (243, 256), "authors": ["Jane M. Gervasio"]},
    14: {"title": "Cardiac Drugs and Nutritional Status", "pages": (257, 270), "authors": ["Honesto M. Poblete Jr.", "Raymond C. Talucci II"]},
    15: {"title": "Drug-Nutrient Interactions Involving Folate", "pages": (271, 284), "authors": ["Leslie Schechter", "Patricia Worthington"]},
    16: {"title": "Effects of Antiepileptics on Nutritional Status", "pages": (285, 300), "authors": ["Mary J. Berg"]},
    17: {"title": "Drug-Nutrient Interactions That Impact Mineral Status", "pages": (301, 330), "authors": ["Sue A. Shapses", "Yvette R. Schlussel", "Mariana Cifuentes"]},
    18: {"title": "Drug-Nutrient Interactions in Infancy and Childhood", "pages": (331, 344), "authors": ["Deborah A. Maka", "Lori Enriquez", "Maria R. Mascarenhas"]},
    19: {"title": "Drug-Nutrient Interaction Considerations in Pregnancy and Lactation", "pages": (345, 362), "authors": ["Kathleen L. Hoover", "Marcia Silkroski", "Leslie Schechter", "Patricia Worthington"]},
    20: {"title": "Drug-Nutrient Interactions in the Elderly", "pages": (363, 412), "authors": ["Tanya C. Knight-Klimas", "Joseph I. Boullata"]},
    21: {"title": "Drug-Nutrient Interactions in Patients With Cancer", "pages": (413, 424), "authors": ["Todd W. Canada"]},
    22: {"title": "Drug-Nutrient Interactions in Transplantation", "pages": (425, 440), "authors": ["Matthew J. Weiss", "Vincent T. Armenti", "Jeanette M. Hasse"]},
    23: {"title": "Drug-Nutrient Interactions and Immune Function", "pages": (441, 478), "authors": ["Adrianne Bendich", "Ronit Zilberboim"]},
    24: {"title": "Drug-Nutrient Interactions in Patients With Chronic Infections", "pages": (479, 498), "authors": ["Steven P. Gelone", "Judith A. O'Donnell"]},
    25: {"title": "Antimicrobial-Nutrient Interactions: An Overview", "pages": (499, 520), "authors": ["Allison Wood Wallace"]},
    26: {"title": "Drug-Nutrient Interactions in Patients Receiving Enteral Nutrition", "pages": (521, 540), "authors": ["Various"]},
}

# Integrative Human Biochemistry (2022)
BIOCHEM_TOC = {
    1: {"title": "Introduction: Life Is Made of Molecules!", "pages": (3, 22), "section_num": "1"},
    2: {"title": "The Chemistry and Physics of Life", "pages": (23, 48), "section_num": "2"},
    2.1: {"title": "The Basics of Chemistry in Cells and Tissues", "pages": (27, 47), "section_num": "2.1"},
    3: {"title": "The Families of Biological Molecules", "pages": (49, 128), "section_num": "3"},
    3.1: {"title": "Lipids and Organization of Supramolecular Assemblies", "pages": (50, 70), "section_num": "3.1"},
    3.3: {"title": "Amino Acids and Their Polymers: Peptides and Proteins", "pages": (95, 128), "section_num": "3.3"},
    3.3.2: {"title": "Structure and Function in Proteins", "pages": (106, 119), "section_num": "3.3.2"},
    3.3.4: {"title": "Enzymes", "pages": (119, 128), "section_num": "3.3.4"},
    4: {"title": "Introduction to Metabolism", "pages": (131, 156), "section_num": "4"},
    5: {"title": "The Regulation of Metabolisms", "pages": (157, 184), "section_num": "5"},
    5.2: {"title": "Inhibition and Activation of Enzymes by Ligands", "pages": (163, 171), "section_num": "5.2"},
    6: {"title": "Energy Conservation in Metabolism: The Mechanisms of ATP Synthesis", "pages": (185, 220), "section_num": "6"},
    6.1: {"title": "Fermentation: The Anaerobic Pathway for ATP Synthesis", "pages": (186, 194), "section_num": "6.1"},
    6.2: {"title": "Oxidative Phosphorylation: The Main Mechanism of ATP Synthesis", "pages": (194, 220), "section_num": "6.2"},
    6.2.3: {"title": "The Electron Transport System", "pages": (203, 216), "section_num": "6.2.3"},
    6.2.4: {"title": "The ATP Synthesis Through Oxidative Phosphorylation", "pages": (212, 220), "section_num": "6.2.4"},
    7: {"title": "Catabolism of the Major Biomolecules", "pages": (223, 257), "section_num": "7"},
    7.2: {"title": "Tricarboxylic Acid Cycle", "pages": (227, 236), "section_num": "7.2"},
    7.3: {"title": "Catabolism of Carbohydrates", "pages": (233, 237), "section_num": "7.3"},
    7.4: {"title": "Catabolism of Lipids", "pages": (237, 257), "section_num": "7.4"},
    7.4.1: {"title": "TAG Mobilization and Fatty Acid Transport", "pages": (238, 240), "section_num": "7.4.1"},
    7.4.6: {"title": "Fatty Acid Conversion to Ketone Bodies", "pages": (246, 248), "section_num": "7.4.6"},
    7.5: {"title": "Catabolism of Amino Acids", "pages": (248, 257), "section_num": "7.5"},
    7.5.2: {"title": "Amino Acid Metabolism in the Liver", "pages": (249, 255), "section_num": "7.5.2"},
    8: {"title": "Metabolic Responses to Hyperglycemia", "pages": (259, 304), "section_num": "8"},
    8.2: {"title": "Biosynthesis of Glycogen", "pages": (266, 276), "section_num": "8.2"},
    8.3: {"title": "Biosynthesis of Lipids", "pages": (276, 294), "section_num": "8.3"},
    8.4: {"title": "Hormonal Responses to Hyperglycemia: Role of Insulin", "pages": (295, 304), "section_num": "8.4"},
    8.4.2: {"title": "Mechanisms of Insulin Action", "pages": (297, 301), "section_num": "8.4.2"},
    9: {"title": "Regulation and Integration of Metabolism During Hypoglycemia", "pages": (305, 340), "section_num": "9"},
    9.2: {"title": "Glycogen Degradation in the Liver", "pages": (312, 319), "section_num": "9.2"},
    9.3: {"title": "Gluconeogenesis", "pages": (319, 330), "section_num": "9.3"},
    9.3.1: {"title": "Gluconeogenesis Reactions", "pages": (320, 327), "section_num": "9.3.1"},
    9.4: {"title": "Hormonal Responses to Hypoglycemia", "pages": (330, 340), "section_num": "9.4"},
    9.4.2: {"title": "Glucocorticoids: Mechanism of Action", "pages": (335, 340), "section_num": "9.4.2"},
    10: {"title": "Regulation and Integration of Metabolism During Physical Activity", "pages": (341, 374), "section_num": "10"},
    10.1: {"title": "Muscle Contraction", "pages": (342, 356), "section_num": "10.1"},
    10.4: {"title": "Muscle Cell Metabolism During Physical Activity", "pages": (356, 374), "section_num": "10.4"},
    11: {"title": "Control of Body Weight and the Modern Metabolic Diseases", "pages": (375, 409), "section_num": "11"},
    11.3: {"title": "Obesity and the Metabolic Syndrome", "pages": (401, 409), "section_num": "11.3"},
}

# ==============================================================================
# CHAPTER EXTRACTION FUNCTIONS
# ==============================================================================

def extract_chapters_from_pdf(file_path: str, doc_type: str) -> List[Document]:
    """
    Extract chapters from PDF based on TOC structure.

    Args:
        file_path: Path to PDF file
        doc_type: One of ["shaw_2020", "preterm_2013", "drug_nutrient", "biochemistry"]

    Returns:
        List of Document objects, one per chapter/section
    """
    # Select appropriate TOC
    toc_map = {
        "shaw_2020": ("Shaw2020", "Clinical Paediatric Dietetics, 5th ed.", SHAW_TOC),
        "preterm_2013": ("PretermNeonate2013", "Nutrition for the Preterm Neonate: A Clinical Perspective", PRETERM_TOC),
        "drug_nutrient": ("DrugNutrient2024", "Handbook of Drug-Nutrient Interactions, 3rd ed.", DRUG_NUTRIENT_TOC),
        "biochemistry": ("IntegrativeBiochem2022", "Integrative Human Biochemistry", BIOCHEM_TOC),
    }

    if doc_type not in toc_map:
        logger.warning(f"⚠️ Unknown doc_type: {doc_type}")
        return []

    source_id, book_title, toc = toc_map[doc_type]

    # Load entire PDF
    try:
        loader = PyPDFLoader(file_path)
        all_pages = loader.load()
    except Exception as e:
        logger.error(f"❌ Failed to load PDF {file_path}: {str(e)}")
        return []

    if not all_pages:
        logger.warning(f"⚠️ No pages extracted from {file_path}")
        return []

    logger.info(f"📄 Loaded {len(all_pages)} pages from {os.path.basename(file_path)}")

    # Extract chapters based on TOC
    chapter_docs = []

    for chapter_key, chapter_info in toc.items():
        chapter_num = chapter_key  # Keep as int or float for section numbers
        page_start, page_end = chapter_info["pages"]

        # Validate page range
        if page_start < 1 or page_end > len(all_pages):
            logger.warning(f"⚠️ Invalid page range for chapter {chapter_num}: ({page_start}, {page_end}) vs {len(all_pages)} pages")
            continue

        # Extract pages for this chapter (0-indexed)
        chapter_pages = all_pages[page_start-1:page_end]

        if not chapter_pages:
            logger.warning(f"⚠️ No pages found for chapter {chapter_num} ({page_start}-{page_end})")
            continue

        # Combine page content
        chapter_text = "\n\n".join([p.page_content for p in chapter_pages if p.page_content.strip()])

        if not chapter_text.strip():
            logger.warning(f"⚠️ Empty content for chapter {chapter_num}")
            continue

        # Determine chunk type (chapter vs section vs protocol)
        chunk_type = "chapter"
        if isinstance(chapter_num, float):
            chunk_type = "section"
        elif doc_type == "shaw_2020" and chapter_num == 31:
            chunk_type = "protocol"  # Emergency regimens

        # Create Document with rich metadata
        chapter_doc = Document(
            page_content=chapter_text,
            metadata={
                "source": source_id,
                "book_title": book_title,
                "chapter_num": int(chapter_num) if isinstance(chapter_num, int) else chapter_num,
                "chapter_title": chapter_info["title"],
                "authors": chapter_info.get("authors", []),
                "page_start": page_start,
                "page_end": page_end,
                "chunk_type": chunk_type,
                "section_num": chapter_info.get("section_num"),
                "document_type": doc_type,
            }
        )

        chapter_docs.append(chapter_doc)
        logger.info(f"✅ Extracted {chunk_type.capitalize()} {chapter_num}: {chapter_info['title']} ({page_end - page_start + 1} pages, {len(chapter_text)} chars)")

    logger.info(f"📊 Total chapters extracted from {os.path.basename(file_path)}: {len(chapter_docs)}")
    return chapter_docs


def get_toc_for_document(doc_type: str) -> Dict[Any, Dict[str, Any]]:
    """
    Retrieve the table of contents for a given document type.
    Useful for debugging and introspection.

    Args:
        doc_type: One of ["shaw_2020", "preterm_2013", "drug_nutrient", "biochemistry"]

    Returns:
        Dictionary mapping chapter numbers to chapter info
    """
    toc_map = {
        "shaw_2020": SHAW_TOC,
        "preterm_2013": PRETERM_TOC,
        "drug_nutrient": DRUG_NUTRIENT_TOC,
        "biochemistry": BIOCHEM_TOC,
    }
    return toc_map.get(doc_type, {})
