# app/components/retrieval_manager.py
import logging
from typing import Dict, Any, List, Optional
from langchain.schema import Document

from app.common.logger import get_logger
from app.common.custom_exception import CustomException

# Reuse hybrid retriever and metadata enricher
from app.components.hybrid_retriever import filtered_retrieval
from app.components.metadata_enricher import MetadataEnricher

logger = get_logger(__name__)


class RetrievalManager:
    """
    Manages all context retrieval operations.
    Connects intent, condition, and profile info to filtered FAISS retrieval.
    """

    def _init_(self):
        self.enricher = MetadataEnricher()

    def retrieve_context(
        self,
        query: str,
        intent: str,
        slots: Optional[Dict[str, Any]] = None,
        condition: Optional[str] = None,
        sources: Optional[List[str]] = None,
        k: int = 5,
    ) -> List[Document]:
        """
        Main entry point for context retrieval.

        Steps:
        1. Build metadata filters based on intent, slots, and condition.
        2. Retrieve documents via hybrid retriever.
        3. Enrich metadata for later reasoning or citation.
        4. Return structured results.
        """
        slots = slots or {}
        filters = self._build_filters(intent, slots, condition)
        try:
            logger.info(f"RetrievalManager: Executing filtered retrieval for intent={intent}")
            results = filtered_retrieval(query=query, filter_candidates=filters, k=k, sources=sources)

            if not results:
                logger.warning(f"No retrieval results found for query='{query[:80]}...' with filters={filters}")
                return []

            enriched_docs = self.enricher.enrich(results)
            logger.info(f"Retrieved and enriched {len(enriched_docs)} documents.")
            return enriched_docs

        except Exception as e:
            logger.error(f"RetrievalManager failed: {str(e)}")
            raise CustomException("RetrievalManager failure", e)

    def _build_filters(self, intent: str, slots: Dict[str, Any], condition: Optional[str]) -> List[Dict[str, Any]]:
        """
        Construct tiered filter candidates depending on the query intent and user profile data.
        The goal is to balance specificity with fallback flexibility.
        """
        filters: List[Dict[str, Any]] = []
        base_filter: Dict[str, Any] = {}

        # Country-specific FCT
        if slots.get("country"):
            base_filter["country"] = slots["country"]

        # Intent-based document type selection
        if intent == "comparison":
            base_filter["doc_type"] = "FCT"
        elif intent in ["recommendation", "therapy"]:
            base_filter["doc_type"] = "clinical_text"
        else:
            base_filter["doc_type"] = "general"

        # Age relevance mapping
        if "age" in slots:
            age_relevance = self._map_age_relevance(slots["age"])
            if age_relevance:
                base_filter["age_relevance"] = age_relevance

        # Condition or therapy area
        if condition:
            base_filter["therapy_area"] = condition
        elif slots.get("diagnosis"):
            base_filter["therapy_area"] = slots["diagnosis"]

        # Medications (for condition-specific mapping)
        if slots.get("medications"):
            base_filter["condition_tags"] = [m.lower() for m in slots["medications"]] if isinstance(slots["medications"], list) else [slots["medications"].lower()]

        # Optional disease or keyword refinement
        if slots.get("disease"):
            base_filter["disease"] = slots["disease"]

        # Primary strict filter
        filters.append(base_filter)

        # Relaxed fallback: remove specific fields to broaden retrieval
        relaxed = base_filter.copy()
        relaxed.pop("therapy_area", None)
        relaxed.pop("condition_tags", None)
        filters.append(relaxed)

        logger.debug(f"Built filters for intent={intent}: {filters}")
        return filters

    def _map_age_relevance(self, age: Any) -> Optional[str]:
        """Map numerical age to age_relevance categories used in metadata"""
        try:
            age_val = int(age)
        except Exception:
            return None

        if age_val < 1:
            return "infant"
        elif 1 <= age_val <= 3:
            return "toddler"
        elif 4 <= age_val <= 9:
            return "child"
        elif 10 <= age_val <= 17:
            return "adolescent"
        elif 18 <= age_val <= 64:
            return "adult"
        else:
            return "elderly"