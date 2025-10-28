# app/components/therapy_generator.py
"""
TherapyGenerator

Orchestrates Steps 2-4 of the therapy flow:
- Step 2: Therapeutic nutrient adjustments from Clinical Paediatric Dietetics
- Step 3: Biochemical context from Integrative Human Biochemistry
- Step 4: Drug-nutrient interaction calculations from Drug-Nutrient Handbook

Usage:
    therapy_gen = TherapyGenerator()

    # Step 2: Therapeutic adjustments
    adjustments = therapy_gen.get_therapeutic_adjustments(
        diagnosis="Type 1 Diabetes",
        baseline_dri={"protein": {"value": 45, "unit": "g"}},
        age=8,
        weight=25
    )

    # Step 3: Biochemical context
    context = therapy_gen.get_biochemical_context(
        diagnosis="Type 1 Diabetes",
        affected_nutrients=["carbohydrate", "protein"]
    )

    # Step 4: Drug-nutrient interactions
    interactions = therapy_gen.calculate_drug_nutrient_interactions(
        medications=["insulin"],
        adjusted_requirements=adjustments
    )
"""

import logging
import re
from typing import Dict, List, Any, Optional
from langchain.schema import Document

logger = logging.getLogger(__name__)


class TherapyGenerator:
    """
    Therapy Generator for Steps 2-4 of therapeutic meal planning.

    Integrates retrieval from:
    - Clinical Paediatric Dietetics (therapeutic adjustments)
    - Integrative Human Biochemistry (metabolic context)
    - Drug-Nutrient Interactions Handbook (medication effects)
    """

    def __init__(self):
        """Initialize Therapy Generator with retrieval components."""
        pass

    # ============================================================================
    # STEP 2: THERAPEUTIC ADJUSTMENTS
    # ============================================================================

    def get_therapeutic_adjustments(
        self,
        diagnosis: str,
        baseline_dri: Dict[str, Dict[str, Any]],
        age: int,
        weight: float
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get condition-specific nutrient adjustments from Clinical Paediatric Dietetics.

        This is STEP 2 of the therapy flow.

        Retrieval Strategy:
        1. Query: "{diagnosis} nutrient requirements CHO protein fat fiber vitamins minerals"
        2. Target: Clinical Paediatric Dietetics chapters matching diagnosis
        3. Parse: Percentage adjustments ("150% energy for CF")
                 Absolute values ("3-4 g/kg protein for CKD")
                 Restrictions ("Restrict Phe <350mg for PKU")
        4. Calculate adjusted values based on baseline

        Args:
            diagnosis: Normalized diagnosis (e.g., "Type 1 Diabetes")
            baseline_dri: DRI baseline from Step 1
            age: Age in years
            weight: Weight in kg

        Returns:
            Dict mapping nutrient to adjustment data:
            {
                "protein": {
                    "baseline": 45,
                    "adjusted": 50,
                    "reason": "Increased needs for T1D growth",
                    "source": "Clinical Paediatric Dietetics Ch12 p456",
                    "unit": "g"
                },
                ...
            }
        """
        logger.info(f"Getting therapeutic adjustments for {diagnosis}")

        # Build retrieval query
        query = f"{diagnosis} nutrient requirements carbohydrate protein fat fiber vitamins minerals"

        # Retrieve from Clinical Paediatric Dietetics
        documents = self._retrieve_for_step2(query, diagnosis)

        # Parse retrieved documents for adjustment patterns
        adjustments = self._parse_therapeutic_adjustments(
            documents=documents,
            baseline_dri=baseline_dri,
            diagnosis=diagnosis,
            age=age,
            weight=weight
        )

        logger.info(f"Retrieved adjustments for {len(adjustments)} nutrients")

        return adjustments

    def _retrieve_for_step2(
        self,
        query: str,
        diagnosis: str,
        k: int = 5
    ) -> List[Document]:
        """
        Retrieve documents from Clinical Paediatric Dietetics for Step 2.

        Args:
            query: Retrieval query
            diagnosis: Diagnosis for filtering
            k: Number of documents to retrieve

        Returns:
            List of Document objects
        """
        from app.components.hybrid_retriever import retrieve_for_therapy_step

        try:
            documents = retrieve_for_therapy_step(
                query=query,
                step_number=2,  # Step 2: therapeutic adjustments
                diagnosis=diagnosis,
                k=k
            )
            return documents
        except Exception as e:
            logger.error(f"Retrieval failed for Step 2: {e}")
            return []

    def _parse_therapeutic_adjustments(
        self,
        documents: List[Document],
        baseline_dri: Dict[str, Dict[str, Any]],
        diagnosis: str,
        age: int,
        weight: float
    ) -> Dict[str, Dict[str, Any]]:
        """
        Parse retrieved documents to extract nutrient adjustments.

        Patterns to detect:
        - Percentage: "150% energy", "120-150% of RDA"
        - Absolute: "3-4 g/kg protein", "2000 IU vitamin D"
        - Range: "1.5-2.0 g/kg", "30-35% fat"
        - Restriction: "Restrict phenylalanine <350mg"

        Args:
            documents: Retrieved documents
            baseline_dri: Baseline DRI values
            diagnosis: Diagnosis
            age: Age
            weight: Weight

        Returns:
            Dict of adjustments per nutrient
        """
        adjustments = {}

        # Combine document content
        combined_text = "\n".join([doc.page_content for doc in documents])

        # For each nutrient in baseline, try to find adjustments
        for nutrient, baseline_data in baseline_dri.items():
            baseline_value = baseline_data.get("value")
            unit = baseline_data.get("unit")

            if baseline_value is None:
                continue

            # Try to find adjustment patterns for this nutrient
            adjustment = self._extract_nutrient_adjustment(
                text=combined_text,
                nutrient=nutrient,
                baseline_value=baseline_value,
                unit=unit,
                weight=weight,
                diagnosis=diagnosis
            )

            if adjustment:
                # Get source citation from documents
                source_citation = self._extract_citation(documents, nutrient)

                adjustments[nutrient] = {
                    "baseline": baseline_value,
                    "adjusted": adjustment["value"],
                    "reason": adjustment["reason"],
                    "source": source_citation,
                    "unit": unit,
                    "adjustment_type": adjustment["type"]  # percentage, absolute, restriction
                }

        # If no adjustments found, keep baseline for all nutrients
        for nutrient, baseline_data in baseline_dri.items():
            if nutrient not in adjustments:
                adjustments[nutrient] = {
                    "baseline": baseline_data.get("value"),
                    "adjusted": baseline_data.get("value"),  # No change
                    "reason": "Standard DRI maintained",
                    "source": "DRI baseline",
                    "unit": baseline_data.get("unit"),
                    "adjustment_type": "none"
                }

        return adjustments

    def _extract_nutrient_adjustment(
        self,
        text: str,
        nutrient: str,
        baseline_value: float,
        unit: str,
        weight: float,
        diagnosis: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract adjustment for a specific nutrient from text.

        Args:
            text: Combined document text
            nutrient: Nutrient name
            baseline_value: Baseline DRI value
            unit: Unit
            weight: Patient weight
            diagnosis: Diagnosis

        Returns:
            Dict with adjusted value, reason, type or None if not found
        """
        # Normalize nutrient aliases
        nutrient_patterns = {
            "energy": ["energy", "calories", "kcal"],
            "protein": ["protein", "pro"],
            "carbohydrate": ["carbohydrate", "cho", "carbs"],
            "fat": ["fat", "lipid"],
            "fiber": ["fiber", "fibre", "dietary fiber"]
        }

        patterns = nutrient_patterns.get(nutrient.lower(), [nutrient])

        # Pattern 1: Percentage adjustment ("150% of RDA", "120-150% energy")
        for pattern in patterns:
            regex = rf"{pattern}[:\s]+(\d+)-?(\d+)?%"
            match = re.search(regex, text, re.IGNORECASE)

            if match:
                pct_low = int(match.group(1))
                pct_high = int(match.group(2)) if match.group(2) else pct_low
                pct_avg = (pct_low + pct_high) / 2

                adjusted_value = baseline_value * (pct_avg / 100)
                return {
                    "value": round(adjusted_value, 1),
                    "reason": f"{pct_avg:.0f}% of baseline for {diagnosis}",
                    "type": "percentage"
                }

        # Pattern 2: Absolute per-kg ("3-4 g/kg protein", "1.5 g/kg")
        for pattern in patterns:
            regex = rf"{pattern}[:\s]+(\d+\.?\d*)-?(\d+\.?\d*)?\s*(?:g|mg|μg)/kg"
            match = re.search(regex, text, re.IGNORECASE)

            if match:
                val_low = float(match.group(1))
                val_high = float(match.group(2)) if match.group(2) else val_low
                val_avg = (val_low + val_high) / 2

                adjusted_value = val_avg * weight
                return {
                    "value": round(adjusted_value, 1),
                    "reason": f"{val_avg} {unit}/kg for {diagnosis}",
                    "type": "absolute_per_kg"
                }

        # Pattern 3: Fixed absolute value ("2000 IU vitamin D")
        for pattern in patterns:
            regex = rf"{pattern}[:\s]+(\d+\.?\d*)\s*(?:IU|mg|μg|g)"
            match = re.search(regex, text, re.IGNORECASE)

            if match:
                adjusted_value = float(match.group(1))
                return {
                    "value": round(adjusted_value, 1),
                    "reason": f"Recommended supplementation for {diagnosis}",
                    "type": "absolute_fixed"
                }

        # No adjustment pattern found
        return None

    def _extract_citation(self, documents: List[Document], nutrient: str) -> str:
        """Extract source citation from documents."""
        if not documents:
            return "Clinical Paediatric Dietetics (source not available)"

        # Get first document metadata
        doc = documents[0]
        metadata = doc.metadata if hasattr(doc, "metadata") else {}

        source = metadata.get("source", "Clinical Paediatric Dietetics")
        chapter = metadata.get("chapter_num", metadata.get("chapter", ""))
        page = metadata.get("page", metadata.get("page_num", ""))

        citation_parts = [source]
        if chapter:
            citation_parts.append(f"Chapter {chapter}")
        if page:
            citation_parts.append(f"p{page}")

        return ", ".join(citation_parts)

    # ============================================================================
    # STEP 3: BIOCHEMICAL CONTEXT
    # ============================================================================

    def get_biochemical_context(
        self,
        diagnosis: str,
        affected_nutrients: List[str]
    ) -> str:
        """
        Get biochemical context explaining metabolic pathways.

        This is STEP 3 of the therapy flow.

        Retrieval Strategy:
        1. Query: "{diagnosis} metabolism {nutrients} pathway enzyme"
        2. Target: Integrative Human Biochemistry chapters
        3. Extract: Metabolic pathway explanations, enzyme deficiencies, absorption issues

        Args:
            diagnosis: Normalized diagnosis
            affected_nutrients: List of nutrients with adjustments

        Returns:
            Contextualized explanation string

        Example:
            "In Type 1 Diabetes, insulin deficiency impairs glucose uptake by cells,
            leading to hyperglycemia. Carbohydrate intake must be carefully matched
            to insulin dosing to maintain glycemic control..."
        """
        logger.info(f"Getting biochemical context for {diagnosis}")

        # Build query
        nutrients_str = " ".join(affected_nutrients[:5])  # Limit to top 5
        query = f"{diagnosis} metabolism {nutrients_str} pathway deficiency absorption"

        # Retrieve from Integrative Human Biochemistry
        documents = self._retrieve_for_step3(query, diagnosis)

        # Extract and summarize context
        context = self._parse_biochemical_context(documents, diagnosis)

        return context

    def _retrieve_for_step3(
        self,
        query: str,
        diagnosis: str,
        k: int = 3
    ) -> List[Document]:
        """Retrieve documents from Integrative Human Biochemistry for Step 3."""
        from app.components.hybrid_retriever import retrieve_for_therapy_step

        try:
            documents = retrieve_for_therapy_step(
                query=query,
                step_number=3,  # Step 3: biochemical context
                diagnosis=diagnosis,
                k=k
            )
            return documents
        except Exception as e:
            logger.error(f"Retrieval failed for Step 3: {e}")
            return []

    def _parse_biochemical_context(
        self,
        documents: List[Document],
        diagnosis: str
    ) -> str:
        """
        Parse biochemical documents to create context explanation.

        Args:
            documents: Retrieved documents
            diagnosis: Diagnosis

        Returns:
            Contextualized explanation
        """
        if not documents:
            return f"Metabolic context for {diagnosis} (detailed information pending retrieval)."

        # Combine top document snippets
        context_parts = []

        for doc in documents[:2]:  # Use top 2 documents
            text = doc.page_content if hasattr(doc, "page_content") else str(doc)

            # Extract relevant sentences (simplified - could use NLP)
            sentences = text.split(".")[:3]  # First 3 sentences
            context_parts.extend([s.strip() + "." for s in sentences if len(s.strip()) > 20])

        if context_parts:
            context = " ".join(context_parts[:3])  # Limit to 3 sentences
            source = self._extract_citation(documents, "")
            return f"{context}\n\nSource: {source}"
        else:
            return f"Metabolic pathways relevant to {diagnosis} include nutrient metabolism and enzyme function."

    # ============================================================================
    # STEP 4: DRUG-NUTRIENT INTERACTIONS
    # ============================================================================

    def calculate_drug_nutrient_interactions(
        self,
        medications: List[str],
        adjusted_requirements: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        """
        Calculate drug-nutrient interactions and adjust requirements.

        This is STEP 4 of the therapy flow.

        Retrieval Strategy:
        1. For each medication:
           - Query: "{medication} nutrient interaction depletion absorption"
           - Target: Drug-Nutrient Interactions Handbook
        2. Parse: Drug-induced depletions ("Metformin → B12 ↓")
                 Timing requirements ("Take iron 2h before levothyroxine")
                 Supplementation needs ("+500 μg B12 daily")

        Args:
            medications: List of medications
            adjusted_requirements: Adjusted requirements from Step 2

        Returns:
            List of interaction notes/warnings
        """
        logger.info(f"Calculating drug-nutrient interactions for {len(medications)} medications")

        interaction_notes = []

        for medication in medications:
            # Retrieve drug-nutrient info
            documents = self._retrieve_for_step4(medication)

            # Parse interactions
            interactions = self._parse_drug_interactions(
                documents=documents,
                medication=medication,
                adjusted_requirements=adjusted_requirements
            )

            interaction_notes.extend(interactions)

        if not interaction_notes:
            interaction_notes.append("No significant drug-nutrient interactions identified.")

        return interaction_notes

    def _retrieve_for_step4(
        self,
        medication: str,
        k: int = 3
    ) -> List[Document]:
        """Retrieve drug-nutrient interaction documents for Step 4."""
        from app.components.hybrid_retriever import retrieve_for_therapy_step

        query = f"{medication} nutrient interaction depletion absorption supplementation"

        try:
            documents = retrieve_for_therapy_step(
                query=query,
                step_number=4,  # Step 4: drug-nutrient
                k=k
            )
            return documents
        except Exception as e:
            logger.error(f"Retrieval failed for Step 4 ({medication}): {e}")
            return []

    def _parse_drug_interactions(
        self,
        documents: List[Document],
        medication: str,
        adjusted_requirements: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        """
        Parse drug-nutrient interaction documents.

        Args:
            documents: Retrieved documents
            medication: Medication name
            adjusted_requirements: Current nutrient requirements

        Returns:
            List of interaction notes
        """
        if not documents:
            return [f"{medication}: No documented nutrient interactions found."]

        notes = []
        combined_text = "\n".join([doc.page_content for doc in documents])

        # Pattern 1: Depletion ("depletes B12", "reduces folate")
        depletion_pattern = r"(?:depletes?|reduces?|decreases?|lowers?)\s+(\w+)"
        depletion_matches = re.findall(depletion_pattern, combined_text, re.IGNORECASE)

        for nutrient in depletion_matches:
            if nutrient.lower() in ["vitamin", "mineral"]:
                continue
            notes.append(f"{medication} → {nutrient} depletion (consider supplementation)")

        # Pattern 2: Timing ("take with food", "2 hours before")
        if "take with food" in combined_text.lower():
            notes.append(f"{medication}: Take with food for better absorption")
        if "empty stomach" in combined_text.lower():
            notes.append(f"{medication}: Take on empty stomach")

        # Pattern 3: Avoid combinations
        if "avoid" in combined_text.lower():
            avoid_pattern = r"avoid\s+(?:taking\s+)?(?:with\s+)?(\w+)"
            avoid_matches = re.findall(avoid_pattern, combined_text, re.IGNORECASE)
            for item in avoid_matches[:2]:
                notes.append(f"{medication}: Avoid taking with {item}")

        # If no specific patterns found, add general note
        if not notes:
            source = self._extract_citation(documents, medication)
            notes.append(f"{medication}: Monitor nutrient status (Source: {source})")

        return notes


# Example usage and testing
if __name__ == "__main__":
    therapy_gen = TherapyGenerator()

    # Test Step 2: Therapeutic adjustments
    baseline_dri = {
        "protein": {"value": 45, "unit": "g"},
        "energy": {"value": 1500, "unit": "kcal"}
    }

    adjustments = therapy_gen.get_therapeutic_adjustments(
        diagnosis="Type 1 Diabetes",
        baseline_dri=baseline_dri,
        age=8,
        weight=25
    )

    print(f"Therapeutic adjustments: {adjustments}")

    # Test Step 3: Biochemical context
    context = therapy_gen.get_biochemical_context(
        diagnosis="Type 1 Diabetes",
        affected_nutrients=["carbohydrate", "protein"]
    )

    print(f"\nBiochemical context: {context}")

    # Test Step 4: Drug-nutrient interactions
    interactions = therapy_gen.calculate_drug_nutrient_interactions(
        medications=["insulin"],
        adjusted_requirements=adjustments
    )

    print(f"\nDrug-nutrient interactions: {interactions}")
