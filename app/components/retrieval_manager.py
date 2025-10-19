# app/components/retrieval_manager.py
"""
RetrievalManager
- Higher-level RAG-layered retrieval controller built on top of hybrid_retriever.py
- Provides:
    * retrieve_context(user_query, intent, condition, profile, k, source_priority, filters)
    * enrich_context_metadata(docs) -> attach/enforce metadata tags (uses metadata_enricher)
    * build_rag_candidates(...) -> list of filter dicts ordered strict->relaxed
    * select_docs_for_llm(...) -> rank / dedupe / trim docs and return final context
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from app.common.logger import get_logger
from app.common.custom_exception import CustomException
from app.components import hybrid_retriever  # uses filtered_retrieval() and retriever
from app.components.metadata_enricher import enrich_chapter_metadata  # already in memory
from langchain.schema import Document

logger = get_logger(__name__)


class RetrievalManager:
    def __init__(self, retriever_wrapper=None):
        """
        Initialize RetrievalManager.
        If retriever_wrapper not provided, uses hybrid_retriever.filtered_retrieval.
        """
        self.retrieval_fn = hybrid_retriever.filtered_retrieval
        self.is_available = hybrid_retriever._retriever_manager.is_available()
        logger.info(f"RetrievalManager initialized (available={self.is_available})")

    # -------------------------------------------------------
    # Public API: retrieve_context
    # -------------------------------------------------------
    def retrieve_context(
        self,
        user_query: str,
        intent: str,
        condition: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
        k: int = 6,
        source_priority: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Perform RAG-layered retrieval.
        Strategy:
          1) Build strict filters based on condition + therapy area + country + age_relevance
          2) Try strict filters (chapter-aware, therapy_area, condition_tags)
          3) If no results, progressively relax filters (drop age, drop therapy_area, only source)
          4) If still none, do semantic-only search (no filter)
          5) Return top-K documents (deduped), enriched via metadata_enricher
        """
        if not self.is_available:
            raise CustomException("Retriever not initialized", None)

        profile = profile or {}
        country = profile.get("country") or (filters or {}).get("country")
        age = profile.get("age")
        therapy_area = None
        if condition:
            therapy_area = self._map_condition_to_therapy_area(condition)

        # Build an ordered set of candidate filter dicts (strict -> relaxed)
        candidate_filters = self._build_rag_candidates(
            condition=condition,
            therapy_area=therapy_area,
            country=country,
            age=age,
            explicit_filters=filters,
            source_priority=source_priority
        )

        # Try each candidate until we get results
        results: List[Document] = []
        for f in candidate_filters:
            try:
                docs = self.retrieval_fn(user_query, f, k=k, sources=f.get("sources") if f.get("sources") else None)
                if docs:
                    logger.info(f"RetrievalManager: got {len(docs)} docs for filter {f}")
                    results = docs
                    break
            except Exception as e:
                logger.exception(f"Retrieval failed for filter {f}: {e}")
                continue

        # If no results, do semantic-only search (empty filter)
        if not results:
            try:
                logger.warning("RAG fallback: semantic-only search (no metadata filter)")
                docs = self.retrieval_fn(user_query, {}, k=k, sources=source_priority or None)
                results = docs or []
            except Exception as e:
                logger.exception(f"Semantic-only retrieval failed: {e}")
                results = []

        # Deduplicate by (source, chapter_num, page_range) and take top-k
        results = self._dedupe_and_rank(results, k=k)

        # Enrich metadata (ensures tags present for LLM citation and later filtering)
        enriched = self.enrich_context_metadata(results)

        return enriched

    # -------------------------------------------------------
    # Build RAG candidate filters
    # -------------------------------------------------------
    def _build_rag_candidates(
        self,
        condition: Optional[str],
        therapy_area: Optional[str],
        country: Optional[str],
        age: Optional[Any],
        explicit_filters: Optional[Dict[str, Any]],
        source_priority: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """
        Produce a prioritized list of filter dicts (strict -> relaxed).
        Each dict is suitable for hybrid_retriever.filtered_retrieval(...)
        """
        explicit_filters = explicit_filters or {}
        candidates: List[Dict[str, Any]] = []

        # 1. Most strict: therapy_area + condition_tags + age_relevance + country + sources
        strict = {}
        if therapy_area:
            strict["therapy_area"] = therapy_area
        if condition:
            strict["condition_tags"] = [condition.lower().replace(" ", "_")]
        if age:
            # convert age to typical labels used in metadata_enricher
            try:
                age_val = int(age)
                age_label = self._age_to_relevance(age_val)
                strict["age_relevance"] = age_label
            except Exception:
                pass
        if country:
            strict["country"] = country
        if explicit_filters.get("doc_type"):
            strict["doc_type"] = explicit_filters["doc_type"]
        if source_priority:
            strict["sources"] = source_priority

        if strict:
            candidates.append(strict)

        # 2. Relax age requirement (still therapy_area + condition)
        relax_age = dict(strict)
        if "age_relevance" in relax_age:
            relax_age.pop("age_relevance", None)
        if relax_age:
            candidates.append(relax_age)

        # 3. Therapy area only + country
        therapy_only = {}
        if therapy_area:
            therapy_only["therapy_area"] = therapy_area
        if country:
            therapy_only["country"] = country
        if therapy_only:
            candidates.append(therapy_only)

        # 4. Condition tags only
        if condition:
            candidates.append({"condition_tags": [condition.lower().replace(" ", "_")]})

        # 5. Fallback to DRI/drug_nutrient sources if doc_type specified in explicit_filters
        if explicit_filters.get("doc_type"):
            candidates.append({"doc_type": explicit_filters["doc_type"], "country": country} if country else {"doc_type": explicit_filters["doc_type"]})

        # 6. Source-priority pass: try each source as its own filter
        if source_priority:
            for s in source_priority:
                candidates.append({"source": s, "country": country} if country else {"source": s})

        # 7. Very relaxed: only country or doc_type hints
        if country:
            candidates.append({"country": country})
        if explicit_filters.get("doc_type"):
            candidates.append({"doc_type": explicit_filters.get("doc_type")})

        # 8. Last resort: empty dict (semantic-only). hybrid_retriever will be given {} directly by retrieve_context.
        candidates.append({})

        # Deduplicate candidate list while preserving order
        seen = set()
        final = []
        for c in candidates:
            # freeze to tuple for hashability
            key = tuple(sorted(c.items()))
            if key not in seen:
                seen.add(key)
                final.append(c)
        logger.debug(f"RAG filter candidates: {final}")
        return final

    # -------------------------------------------------------
    # Enrich metadata (calls metadata_enricher but ensures safe handling)
    # -------------------------------------------------------
    def enrich_context_metadata(self, docs: List[Document]) -> List[Document]:
        """
        Ensure each Document has enriched metadata (condition_tags, age_relevance, therapy_area, etc.)
        Uses enrich_chapter_metadata() from metadata_enricher where doc.metadata.document_type is known.
        """
        enriched_docs = []
        for doc in docs or []:
            try:
                doc_type = doc.metadata.get("document_type")
                if doc_type:
                    # enrich_chapter_metadata expects Document + doc_type string
                    enriched = enrich_chapter_metadata(doc, doc_type)
                    enriched_docs.append(enriched)
                else:
                    enriched_docs.append(doc)
            except Exception as e:
                logger.exception(f"Failed to enrich metadata for doc {doc.metadata.get('chapter_title','?')}: {e}")
                enriched_docs.append(doc)
        return enriched_docs

    # -------------------------------------------------------
    # Utilities: dedupe/rank
    # -------------------------------------------------------
    def _dedupe_and_rank(self, docs: List[Document], k: int = 6) -> List[Document]:
        """
        Deduplicate by (source, chapter_num, page_start) and return top-k.
        Ranking strategy: prefer chapter docs (protocols), then by page_count (longer), then by source priority.
        """
        seen = set()
        ranked = []
        # Simple scoring
        def score_doc(d: Document) -> Tuple[int, int]:
            chunk_type = d.metadata.get("chunk_type", "")
            page_count = (d.metadata.get("page_end',0") - d.metadata.get("page_start',0")) if isinstance(d.metadata.get("page_start"), int) else 0
            score1 = 2 if chunk_type == "protocol" else 1 if chunk_type == "chapter" else 0
            return (score1, page_count)

        # sort by score descending
        docs_sorted = sorted(docs, key=lambda d: score_doc(d), reverse=True)
        for d in docs_sorted:
            key = (d.metadata.get("source"), d.metadata.get("chapter_num"), d.metadata.get("page_start"))
            if key not in seen:
                seen.add(key)
                ranked.append(d)
            if len(ranked) >= k:
                break
        return ranked

    # -------------------------------------------------------
    # Helpers
    # -------------------------------------------------------
    def _map_condition_to_therapy_area(self, condition: str) -> Optional[str]:
        """
        Map free-text condition to canonical therapy_area keys used in metadata_enricher.
        Minimal mapping for the therapy set you specified.
        """
        if not condition:
            return None
        c = condition.lower()
        if "preterm" in c or "premature" in c or "nicu" in c:
            return "preterm"
        if "type 1" in c or "t1d" in c or "diabetes" in c:
            return "t1d"
        if "food allergy" in c or "allergy" in c:
            return "food_allergy"
        if "cystic fibrosis" in c or "cf" in c:
            return "cf"
        if "pku" in c or "msud" in c or "galactosemia" in c or "inborn error" in c:
            return "iem"
        if "epile" in c or "seizure" in c:
            return "epilepsy"
        if "kidney" in c or "ckd" in c or "renal" in c:
            return "ckd"
        if "ibd" in c or "crohn" in c or "ulcerative" in c or "gerd" in c or "gastro" in c:
            return "gi_disorders"
        return None

    def _age_to_relevance(self, age: int) -> List[str]:
        """
        Return approximate 'age_relevance' labels used in metadata_enricher.
        E.g. preterm, 0-2y, 3-5y, 6-12y, 13-18y, all_ages
        """
        if age < 0:
            return []
        if age < 1:
            return ["preterm", "0-12mo_corrected"]
        if age < 3:
            return ["0-2y"]
        if age < 6:
            return ["3-5y"]
        if age < 13:
            return ["6-12y"]
        if age < 19:
            return ["13-18y"]
        return ["all_ages"]