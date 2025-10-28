# app/components/citation_manager.py
"""
CitationManager

Manages accumulation and formatting of source citations throughout therapy/recommendation flows.
Supports grouped citations by source type for clean presentation.

Usage:
    citations = CitationManager()
    citations.add_citation("Clinical Paediatric Dietetics", chapter="12", page="456", context="T1D requirements")
    citations.add_citation("WHO/FAO DRI", context="age 8, male")
    formatted = citations.get_grouped_citations()
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """Single citation entry"""
    source: str
    chapter: Optional[str] = None
    page: Optional[str] = None
    context: Optional[str] = None
    source_type: Optional[str] = None  # "dri", "clinical", "biochemical", "drug_nutrient", "fct"

    def __str__(self) -> str:
        """Format citation for display"""
        parts = [self.source]

        if self.chapter:
            parts.append(f"Chapter {self.chapter}")

        if self.page:
            parts.append(f"p{self.page}")

        if self.context:
            parts.append(f"({self.context})")

        return ", ".join(parts)


class CitationManager:
    """
    Manages citations throughout therapy generation flow.

    Features:
    - Add citations with metadata (source, chapter, page, context)
    - Automatic source type classification
    - Grouped formatting by source type
    - Deduplication of identical citations
    """

    # Source type classification patterns
    SOURCE_TYPE_PATTERNS = {
        "dri": ["dri", "dietary reference", "who", "fao", "rda", "ai"],
        "clinical": ["clinical paediatric dietetics", "pediatric dietetics", "paediatric nutrition", "preterm neonate"],
        "biochemical": ["integrative human biochemistry", "biochemistry", "metabolism"],
        "drug_nutrient": ["drug-nutrient", "drug nutrient", "medication", "pharmaceutical"],
        "fct": ["food composition table", "fct", "composition database"]
    }

    SOURCE_TYPE_DISPLAY = {
        "dri": "Dietary Reference Intakes",
        "clinical": "Clinical Guidelines",
        "biochemical": "Biochemical Context",
        "drug_nutrient": "Drug-Nutrient Interactions",
        "fct": "Food Composition Tables"
    }

    def __init__(self):
        self.citations: List[Citation] = []
        self._citation_hashes = set()  # For deduplication

    def add_citation(
        self,
        source: str,
        chapter: Optional[str] = None,
        page: Optional[str] = None,
        context: Optional[str] = None,
        source_type: Optional[str] = None
    ) -> None:
        """
        Add a citation with automatic deduplication.

        Args:
            source: Source name (e.g., "Clinical Paediatric Dietetics")
            chapter: Chapter number/name (optional)
            page: Page number(s) (optional)
            context: Additional context (e.g., "T1D requirements")
            source_type: Override automatic source type classification
        """
        # Create citation hash for deduplication
        citation_hash = f"{source}|{chapter}|{page}|{context}"

        if citation_hash in self._citation_hashes:
            logger.debug(f"Duplicate citation skipped: {source}")
            return

        # Auto-classify source type if not provided
        if source_type is None:
            source_type = self._classify_source_type(source)

        citation = Citation(
            source=source,
            chapter=chapter,
            page=page,
            context=context,
            source_type=source_type
        )

        self.citations.append(citation)
        self._citation_hashes.add(citation_hash)
        logger.debug(f"Citation added: {citation}")

    def _classify_source_type(self, source: str) -> str:
        """
        Automatically classify source type based on source name.

        Args:
            source: Source name

        Returns:
            Source type: "dri", "clinical", "biochemical", "drug_nutrient", "fct", or "other"
        """
        source_lower = source.lower()

        for source_type, patterns in self.SOURCE_TYPE_PATTERNS.items():
            if any(pattern in source_lower for pattern in patterns):
                return source_type

        return "other"

    def get_citations_by_type(self, source_type: str) -> List[Citation]:
        """
        Get all citations of a specific type.

        Args:
            source_type: Type of source ("dri", "clinical", etc.)

        Returns:
            List of citations matching the type
        """
        return [c for c in self.citations if c.source_type == source_type]

    def get_grouped_citations(self) -> str:
        """
        Format citations grouped by source type.

        Returns:
            Formatted citation string with emoji headers
        """
        if not self.citations:
            return ""

        grouped: Dict[str, List[Citation]] = {}

        # Group citations by type
        for citation in self.citations:
            source_type = citation.source_type or "other"
            if source_type not in grouped:
                grouped[source_type] = []
            grouped[source_type].append(citation)

        # Format output
        output = ["📚 SOURCES:"]

        # Priority order for display
        priority_order = ["dri", "clinical", "biochemical", "drug_nutrient", "fct", "other"]

        for source_type in priority_order:
            if source_type not in grouped:
                continue

            # Get display name
            display_name = self.SOURCE_TYPE_DISPLAY.get(source_type, "Other Sources")

            # Format citations for this type
            citations_str = []
            for citation in grouped[source_type]:
                citations_str.append(f"  • {citation}")

            if citations_str:
                output.append(f"\n{display_name}:")
                output.extend(citations_str)

        return "\n".join(output)

    def get_simple_list(self) -> List[str]:
        """
        Get citations as simple list of strings.

        Returns:
            List of formatted citation strings
        """
        return [str(c) for c in self.citations]

    def clear(self) -> None:
        """Clear all citations"""
        self.citations.clear()
        self._citation_hashes.clear()
        logger.debug("All citations cleared")

    def count(self) -> int:
        """Get total citation count"""
        return len(self.citations)

    def has_citations(self) -> bool:
        """Check if any citations exist"""
        return len(self.citations) > 0

    def get_summary(self) -> Dict[str, int]:
        """
        Get citation count summary by type.

        Returns:
            Dict mapping source_type to count
        """
        summary: Dict[str, int] = {}

        for citation in self.citations:
            source_type = citation.source_type or "other"
            summary[source_type] = summary.get(source_type, 0) + 1

        return summary


# Example usage and testing
if __name__ == "__main__":
    # Test citation manager
    citations = CitationManager()

    # Add various citations
    citations.add_citation("WHO/FAO Dietary Reference Intakes", context="age 8, male")
    citations.add_citation("Clinical Paediatric Dietetics", chapter="12", page="456-460", context="Type 1 Diabetes")
    citations.add_citation("Integrative Human Biochemistry", page="789", context="Insulin metabolism")
    citations.add_citation("Handbook of Drug-Nutrient Interactions", page="89", context="Metformin-B12")
    citations.add_citation("Kenya Food Composition Table", context="2018 edition")

    # Test deduplication
    citations.add_citation("WHO/FAO Dietary Reference Intakes", context="age 8, male")  # Duplicate

    print(citations.get_grouped_citations())
    print(f"\nTotal citations: {citations.count()}")
    print(f"Summary: {citations.get_summary()}")
