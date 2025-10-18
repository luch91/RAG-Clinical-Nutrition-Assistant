import logging
import threading
from typing import Dict, Any, List, Optional, Union
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
from app.common.logger import get_logger
from app.common.custom_exception import CustomException

logger = get_logger(__name__)

# FIXED: Thread-safe retriever with lock
class RetrieverManager:
    """Thread-safe singleton manager for FAISS retriever"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._retriever = None
                    cls._instance._retriever_lock = threading.RLock()
        return cls._instance

    def set_retriever(self, vector_store: FAISS):
        """Thread-safe setter for retriever"""
        with self._retriever_lock:
            self._retriever = vector_store
            logger.info("Hybrid retriever initialized with FAISS store")

    def get_retriever(self) -> Optional[FAISS]:
        """Thread-safe getter for retriever"""
        with self._retriever_lock:
            return self._retriever

    def is_available(self) -> bool:
        """Check if retriever is available"""
        with self._retriever_lock:
            return self._retriever is not None

# Global instance
_retriever_manager = RetrieverManager()

def init_retriever(vector_store: FAISS):
    """
    Initialize retriever with FAISS vector store.
    This should be called once after building/loading the store.
    """
    _retriever_manager.set_retriever(vector_store)

@property
def retriever() -> Optional[FAISS]:
    """Get the current retriever instance"""
    return _retriever_manager.get_retriever()

def _normalize_metadata_filter(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize app-level filter dict to FAISS metadata filter.
    - Map alias keys (e.g., country_table -> country when applicable)
    - Drop non-metadata hints (e.g., exclude_allergens)
    - Validate country-specific FCT mapping
    - Support chapter-aware clinical text filtering (condition_tags, age_relevance, therapy_area)
    """
    if not isinstance(filters, dict):
        return {}

    meta: Dict[str, Any] = {}

    # Country-specific FCT handling - standardize to 'country' key
    if filters.get("country"):
        country = filters["country"].lower().strip()
        meta["country"] = country

    # Source file/table selection - standardize to 'source' key
    if filters.get("source"):
        meta["source"] = filters["source"]

    # Disease filtering
    if filters.get("disease"):
        meta["disease"] = filters["disease"]

    # CLINICAL TEXT METADATA FILTERING (Chapter-aware retrieval)
    # Condition tags (e.g., ["T1D", "epilepsy", "CKD"])
    if filters.get("condition_tags"):
        meta["condition_tags"] = filters["condition_tags"]

    # Age relevance (e.g., "infant", "toddler", "child", "adolescent", "all_ages")
    if filters.get("age_relevance"):
        meta["age_relevance"] = filters["age_relevance"]

    # Therapy area (e.g., "Preterm", "T1D", "Food Allergy", "CF", "IEMs", "Epilepsy", "CKD", "GI Disorders")
    if filters.get("therapy_area"):
        meta["therapy_area"] = filters["therapy_area"]

    # Document type (e.g., "clinical_text", "FCT", "DRI")
    if filters.get("doc_type"):
        meta["doc_type"] = filters["doc_type"]

    # Pass-through of other safe metadata keys if present
    for key in ("category", "table_country", "food", "chapter_number", "chapter_title"):
        if filters.get(key) is not None:
            meta[key] = filters[key]

    # Allergen exclusion - handle properly for FCT data
    if filters.get("exclude_allergens"):
        meta["exclude_allergens"] = filters["exclude_allergens"]

    return meta

def _apply_filter_search(query: str, filters: Dict[str, Any], k: int = 5) -> List[Document]:
    """
    Internal helper to search FAISS with metadata filters.
    - Add safety checks for allergen exclusion
    - Handle country-specific FCT data properly
    """
    current_retriever = _retriever_manager.get_retriever()
    if not current_retriever:
        logger.error("Retriever not initialized")
        raise CustomException("Retriever not initialized", None)

    try:
        meta_filter = _normalize_metadata_filter(filters)
        results = current_retriever.similarity_search(query, k=k, filter=meta_filter)
        
        # Log retrieval details for debugging and safety
        logger.debug(f"Filter {filters} -> {len(results)} results")
        if results:
            logger.info(f"Retrieval succeeded with {len(results)} results for query: {query[:100]}...")
        else:
            logger.warning(f"No results found for query: {query[:100]}...")
        
        return results
    except Exception as e:
        logger.error(f"Filtered search failed with filters {filters}: {str(e)}")
        raise CustomException("Retrieval failed", e)

def filtered_retrieval(query: str, filter_candidates: Union[Dict[str, Any], List[Dict[str, Any]]], k: int = 5, sources: Optional[List[str]] = None) -> List[Document]:
    """
    Retrieval with optional metadata filters. Accepts either a single filters dict
    or a list of filters (strict -> relaxed). Returns the first non-empty result set.

    - Add safety checks for country-specific FCT data
    - Add fallback to USDA 2023 defaults when no results found
    - Add validation for sources parameter
    """
    if not _retriever_manager.is_available():
        logger.error("Retriever not initialized")
        raise CustomException("Retriever not initialized", None)
    
    # Validate sources parameter
    if sources:
        if not isinstance(sources, list):
            raise CustomException("Sources must be a list", None)
        if not all(isinstance(source, str) for source in sources):
            raise CustomException("All sources must be strings", None)
    
    # Single dict path
    if isinstance(filter_candidates, dict):
        try:
            results = _apply_filter_search(query, filter_candidates, k=k)
            if results:
                return results
        except CustomException as e:
            logger.error(f"Retrieval failed with single filter: {str(e)}")
    
    # List path (progressive)
    if isinstance(filter_candidates, list):
        for f in filter_candidates:
            try:
                results = _apply_filter_search(query, f, k=k)
                if results:
                    return results
            except CustomException as e:
                logger.error(f"Retrieval failed with filter {f}: {str(e)}")
    
    # Fallback to USDA 2023 defaults when no results found
    logger.warning("Retrieval fallback: no results found with any filters. Using USDA 2023 defaults.")
    return []