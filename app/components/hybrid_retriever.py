# app/components/hybrid_retriever.py
import logging
import threading
import os
import pickle
from typing import Dict, Any, List, Optional, Union, Tuple
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
from app.common.logger import get_logger
from app.common.custom_exception import CustomException
from app.components.embeddings import get_embedding_model

logger = get_logger(__name__)

# Optional BM25 fallback (lightweight)
try:
    from rank_bm25 import BM25Okapi
except Exception as e:
    BM25Okapi = None
    logger.warning("rank_bm25 not available; BM25 fallback disabled. Install 'rank_bm25' for sparse retrieval.")

# ---------------------------
# Retriever singleton manager
# ---------------------------
class RetrieverManager:
    """Thread-safe singleton manager for FAISS retriever + BM25 fallback"""
    _instance = None
    _lock = threading.Lock()

    def _new_(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls.instance = super().new_(cls)
                    cls._instance._retriever = None
                    cls._instance._retriever_lock = threading.RLock()
                    # bm25 structures
                    cls._instance._bm25 = None
                    cls._instance._bm25_corpus = []
                    cls._instance._bm25_tokenized = []
                    cls._instance._bm25_docs = []
                    cls._instance._embedding_model = None
        return cls._instance

    # -------------------------
    # FAISS setter/getter
    # -------------------------
    def set_retriever(self, vector_store: FAISS):
        with self._retriever_lock:
            self._retriever = vector_store
            logger.info("Hybrid retriever initialized with FAISS store")

    def get_retriever(self) -> Optional[FAISS]:
        with self._retriever_lock:
            return self._retriever

    def is_available(self) -> bool:
        with self._retriever_lock:
            return self._retriever is not None

    # -------------------------
    # BM25 helpers
    # -------------------------
    def build_bm25_from_docs(self, docs: List[Document]):
        """
        Build BM25 structures from a list of Document objects (or dict-like objects
        with .page_content and .metadata).
        """
        if BM25Okapi is None:
            logger.warning("BM25Okapi not installed; cannot build BM25 index.")
            self._bm25 = None
            return

        corpus = []
        doc_objs = []
        for d in docs:
            text = getattr(d, "page_content", None) or d.metadata.get("text") or d.metadata.get("content") or ""
            title = d.metadata.get("title") or d.metadata.get("food") or ""
            # store combined title+text to improve keyword hits
            combined = (title + " " + text).strip()
            if combined:
                corpus.append(combined)
                doc_objs.append(d)

        # Basic tokenization - whitespace & lowercase. Customize for better tokenization if needed.
        tokenized = [c.lower().split() for c in corpus]
        self._bm25_corpus = corpus
        self._bm25_tokenized = tokenized
        self._bm25_docs = doc_objs
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index built with {len(tokenized)} docs")

    def bm25_search(self, query: str, k: int = 5) -> List[Document]:
        """Return top-k Document objects from BM25 ranking"""
        if BM25Okapi is None or self._bm25 is None:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        top_n = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [self._bm25_docs[i] for i in top_n]

    # -------------------------
    # Embedding model helper (used for rebuild)
    # -------------------------
    def get_embedding_model(self):
        if self._embedding_model is None:
            # Initialize embedding model (default device 'cpu' - can be adapted)
            self._embedding_model = get_embedding_model()
        return self._embedding_model

# global instance
_retriever_manager = RetrieverManager()

# ---------------------------
# Metadata normalization (unchanged, but kept here)
# ---------------------------
def _normalize_metadata_filter(filters: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(filters, dict):
        return {}

    meta: Dict[str, Any] = {}

    if filters.get("country"):
        country = filters["country"].lower().strip()
        meta["country"] = country

    if filters.get("source"):
        meta["source"] = filters["source"]

    if filters.get("disease"):
        meta["disease"] = filters["disease"]

    if filters.get("condition_tags"):
        meta["condition_tags"] = filters["condition_tags"]

    if filters.get("age_relevance"):
        meta["age_relevance"] = filters["age_relevance"]

    if filters.get("therapy_area"):
        meta["therapy_area"] = filters["therapy_area"]

    if filters.get("doc_type"):
        meta["doc_type"] = filters["doc_type"]

    for key in ("category", "table_country", "food", "chapter_number", "chapter_title"):
        if filters.get(key) is not None:
            meta[key] = filters[key]

    if filters.get("exclude_allergens"):
        meta["exclude_allergens"] = filters["exclude_allergens"]

    return meta

# ---------------------------
# FAISS load with self-healing rebuild
# ---------------------------
def load_faiss_index(index_dir: Union[str, Path], cache_dir: Union[str, Path] = "Cache/embedding_chunks/") -> Optional[FAISS]:
    """
    Attempt to load a FAISS vector store from index_dir.
    If loading fails, try to rebuild from cached embedding chunks found under cache_dir.
    Returns FAISS object or raises CustomException if rebuild fails.
    """
    index_dir = Path(index_dir)
    cache_dir = Path(cache_dir)

    # Common LangChain FAISS pattern: the vector store object is stored via FAISS.load_local(...)
    try:
        # Attempt flexible loading: user may store index as files in index_dir
        if index_dir.exists():
            # try to load via classmethod if available
            try:
                vs = FAISS.load_local(str(index_dir))
                logger.info("FAISS index loaded successfully from %s", index_dir)
                return vs
            except Exception:
                # try older pattern: pickle
                try:
                    pkl_path = index_dir / "index.pkl"
                    if pkl_path.exists():
                        with open(pkl_path, "rb") as fh:
                            vs = pickle.load(fh)
                            logger.info("FAISS vector store loaded from pickle: %s", pkl_path)
                            return vs
                except Exception as e2:
                    logger.warning("Failed to load FAISS via pickle: %s", e2)

        raise FileNotFoundError("FAISS index not found or failed to load.")

    except Exception as load_err:
        logger.error("FAISS load failed: %s. Attempting self-heal from cache...", load_err)

        # Attempt rebuild from cache
        try:
            vs = _rebuild_faiss_from_cache(cache_dir, index_dir)
            logger.info("FAISS rebuilt successfully from cache.")
            return vs
        except Exception as rebuild_err:
            logger.error("Rebuild from cache failed: %s", rebuild_err)
            raise CustomException("Failed to load or rebuild FAISS index", rebuild_err)

def _rebuild_faiss_from_cache(cache_dir: Union[str, Path], persist_dir: Union[str, Path]) -> FAISS:
    """
    Rebuild FAISS vector store from cached embedding chunks.
    Expectation: cache files are pickles (.pkl) or .npz files containing lists of records:
    Each record should be either:
     - {'id': str, 'text': str, 'metadata': dict, 'embedding': list/np.array}  (precomputed embeddings), OR
     - {'id':str, 'text': str, 'metadata': dict}  (raw text -> will compute embeddings)
    """
    cache_dir = Path(cache_dir)
    persist_dir = Path(persist_dir)
    if not cache_dir.exists():
        raise FileNotFoundError(f"Cache directory does not exist: {cache_dir}")

    # Collect all chunk files
    chunk_files = sorted([p for p in cache_dir.iterdir() if p.suffix in (".pkl", ".pickle", ".npz", ".json")])
    if not chunk_files:
        raise FileNotFoundError(f"No embedding chunk files found in {cache_dir}")

    all_texts = []
    all_metadatas = []
    all_embeddings = []
    have_embeddings = False

    for f in chunk_files:
        try:
            if f.suffix in (".pkl", ".pickle"):
                with open(f, "rb") as fh:
                    data = pickle.load(fh)
            elif f.suffix == ".npz":
                import numpy as np
                arr = np.load(str(f), allow_pickle=True)
                data = arr.tolist()
            else:
                # try json
                import json
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
        except Exception as e:
            logger.warning("Failed to read cache chunk %s: %s", f, e)
            continue

        # Accept multiple shapes
        if isinstance(data, dict) and data.get("items"):
            data = data["items"]

        for rec in data:
            # rec may be a dict-like row
            text = rec.get("text") or rec.get("page_content") or rec.get("content") or rec.get("title") or ""
            meta = rec.get("metadata") or rec.get("meta") or {"source_file": str(f)}
            emb = rec.get("embedding") or None
            if text:
                all_texts.append(text)
                all_metadatas.append(meta)
                if emb is not None:
                    have_embeddings = True
                    all_embeddings.append(emb)

    if not all_texts:
        raise ValueError("No textual records discovered in cache chunks.")

    # If embeddings present in cache, use them, otherwise compute embeddings from texts
    embedding_model = _retriever_manager.get_embedding_model()
    try:
        if have_embeddings and len(all_embeddings) == len(all_texts):
            # Build FAISS using from_embeddings if available
            try:
                vs = FAISS.from_embeddings(embeddings=all_embeddings, metadatas=all_metadatas)
                # attempt to persist
                persist_dir.mkdir(parents=True, exist_ok=True)
                vs.save_local(str(persist_dir))
                _retriever_manager.set_retriever(vs)
                return vs
            except Exception:
                # fallback: compute embeddings instead
                logger.warning("FAISS.from_embeddings not supported or failed; will compute embeddings anew.")
        # Compute embeddings using embedding model
        logger.info("Computing embeddings for %d cached documents (this may take some time)...", len(all_texts))
        embedder = embedding_model if embedding_model is not None else get_embedding_model()
        # Some embedding wrappers expect a list of texts and return list of vectors
        embeddings_vectors = embedder.embed_documents(all_texts)
        # Build FAISS from texts+embeddings
        vs = FAISS.from_texts(all_texts, embedder, metadatas=all_metadatas)
        persist_dir.mkdir(parents=True, exist_ok=True)
        try:
            vs.save_local(str(persist_dir))
        except Exception as e_save:
            logger.warning("Failed to save rebuilt FAISS locally: %s", e_save)

        _retriever_manager.set_retriever(vs)
        return vs
    except Exception as e:
        logger.exception("Rebuild failed: %s", e)
        raise

# ---------------------------
# Internal helper to run FAISS similarity search with metadata
# ---------------------------
def _apply_filter_search_faiss(query: str, filters: Dict[str, Any], k: int = 5) -> List[Document]:
    current_retriever = _retriever_manager.get_retriever()
    if not current_retriever:
        logger.error("Retriever not initialized")
        raise CustomException("Retriever not initialized", None)

    try:
        meta_filter = _normalize_metadata_filter(filters)
        results = current_retriever.similarity_search(query, k=k, filter=meta_filter)
        logger.debug(f"FAISS Filter {filters} -> {len(results)} results")
        return results
    except Exception as e:
        logger.error("FAISS similarity search failed: %s", e)
        # Signal caller to allow BM25 fallback
        raise

# ---------------------------
# Public hybrid filtered_retrieval (tiered hybrid)
# ---------------------------
def filtered_retrieval(query: str,
                       filter_candidates: Union[Dict[str, Any], List[Dict[str, Any]]],
                       k: int = 5,
                       use_bm25_fallback: bool = True,
                       faiss_score_threshold: float = 0.55) -> List[Document]:
    """
    Tiered hybrid retrieval:
     1) Try FAISS (semantic) with provided filters (single dict or progressive list).
     2) If FAISS returns no results OR average similarity confidence low -> run BM25 fallback (keyword).
     3) Merge results (deduplicate) and return top-k.

    Args:
        query: user query
        filter_candidates: dict or list of dicts (strict -> relaxed)
        k: number of results to return
        use_bm25_fallback: whether to run BM25 when FAISS is weak
        faiss_score_threshold: heuristic threshold (0-1). If mean top score < threshold, consider FAISS weak.
    """
    # First attempt FAISS if available
    faiss_results: List[Document] = []
    bm25_results: List[Document] = []

    # Ensure retriever available - attempt to auto-load from expected path if currently missing
    if not _retriever_manager.is_available():
        # try common locations (Vector_store/db_faiss/)
        try:
            logger.info("Retriever unavailable — attempting to load default FAISS index from Vector_store/db_faiss/")
            _ = load_faiss_index(Path("Vector_store/db_faiss/"))
        except Exception as e:
            logger.warning("Auto-load FAISS failed: %s", e)

    # Run FAISS progressive filters
    if _retriever_manager.is_available():
        try:
            if isinstance(filter_candidates, dict):
                faiss_results = _apply_filter_search_faiss(query, filter_candidates, k=k)
            elif isinstance(filter_candidates, list):
                for f in filter_candidates:
                    try:
                        faiss_results = _apply_filter_search_faiss(query, f, k=k)
                        if faiss_results:
                            break
                    except Exception:
                        continue
            else:
                faiss_results = _apply_filter_search_faiss(query, {}, k=k)
        except Exception as e:
            logger.debug("FAISS search error (will consider BM25): %s", e)
            faiss_results = []

    # Heuristic: consider FAISS weak if empty or low mean similarity if available metadata provides score.
    faiss_is_weak = False
    if not faiss_results:
        faiss_is_weak = True
    else:
        # Try to estimate confidence: for LangChain FAISS documents there may not be direct similarity scores.
        # We'll use a basic heuristic: if results returned but appear non-specific, still allow BM25 to run when asked.
        # (You can later add cross-encoder rerank or expose scores from FAISS retrieval code.)
        pass

    # If FAISS weak and BM25 allowed, run BM25 fallback
    if (faiss_is_weak or use_bm25_fallback) and BM25Okapi is not None:
        try:
            # If BM25 index not built, attempt to build it using a sample from FAISS index (or cached sample)
            if _retriever_manager._bm25 is None:
                # Attempt to seed BM25 from FAISS store (top 200 docs)
                try:
                    # retrieve unfiltered bulk: few common texts - this relies on vector store supporting .similarity_search with empty filter
                    sample_docs = []
                    if _retriever_manager.is_available():
                        try:
                            sample_docs = _retriever_manager.get_retriever().similarity_search(query, k=200)
                        except Exception:
                            sample_docs = _retriever_manager.get_retriever().similarity_search(" ", k=200)
                    # if still empty, try to load cached chunks
                    if not sample_docs:
                        # try to read a small number of cached docs from Cache/embedding_chunks/
                        cache_dir = Path("Cache/embedding_chunks")
                        if cache_dir.exists():
                            # re-use loader from rebuild to extract textual records
                            sample_docs = []
                            for f in sorted(cache_dir.iterdir())[:10]:
                                try:
                                    import pickle, json
                                    if f.suffix in (".pkl", ".pickle"):
                                        recs = pickle.load(open(f, "rb"))
                                    elif f.suffix == ".json":
                                        recs = json.load(open(f, "r", encoding="utf-8"))
                                    else:
                                        recs = []
                                except Exception:
                                    recs = []
                                for rec in (recs or [])[:20]:
                                    text = rec.get("text") or rec.get("page_content") or rec.get("content") or ""
                                    meta = rec.get("metadata") or {}
                                    if text:
                                        # wrap minimal Document-like object
                                        d = Document(page_content=text, metadata=meta)
                                        sample_docs.append(d)
                                if len(sample_docs) >= 200:
                                    break
                    if sample_docs:
                        _retriever_manager.build_bm25_from_docs(sample_docs)
                except Exception as e_build:
                    logger.debug("BM25 seeding failed: %s", e_build)

            bm25_results = _retriever_manager.bm25_search(query, k=k)
        except Exception as e:
            logger.warning("BM25 fallback failed: %s", e)
            bm25_results = []

    # Merge results: prefer FAISS order, then BM25, deduplicate by metadata text/title
    merged: List[Document] = []
    seen = set()

    def doc_id_key(d: Document) -> str:
        # build dedupe key from id-like metadata or content snippet
        mid = getattr(d, "metadata", {}).get("id") or getattr(d, "metadata", {}).get("food") or getattr(d, "metadata", {}).get("title")
        if mid:
            return str(mid)
        # fallback content snippet
        cont = getattr(d, "page_content", "") or getattr(d, "metadata", {}).get("text", "")
        return cont[:200]

    for d in (faiss_results or []):
        kkey = doc_id_key(d)
        if kkey not in seen:
            merged.append(d)
            seen.add(kkey)
            if len(merged) >= k:
                return merged

    for d in (bm25_results or []):
        kkey = doc_id_key(d)
        if kkey not in seen:
            merged.append(d)
            seen.add(kkey)
            if len(merged) >= k:
                return merged

    return merged

# ---------------------------
# Convenience: initialize retriever externally
# ---------------------------
def init_retriever(vector_store: FAISS):
    _retriever_manager.set_retriever(vector_store)

# ---------------------------
# Convenience property for direct access
# ---------------------------
@property
def retriever() -> Optional[FAISS]:
    return _retriever_manager.get_retriever()