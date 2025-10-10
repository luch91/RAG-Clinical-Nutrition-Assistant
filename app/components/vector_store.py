# app/components/vector_store.py
import os
import gc
import torch
from typing import List, Optional
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from app.components.embeddings import get_embedding_model
from app.config.config import DB_FAISS_PATH, CHUNKS_CACHE_PATH
from app.common.logger import get_logger

logger = get_logger(__name__)

def save_vector_store(documents: List[Document]) -> bool:
    """
    Build and save a FAISS vector store from Document objects created by pdf_loader.py.
    Must be called AFTER pdf_loader.py has generated cache/chunks.pkl.
    """
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(DB_FAISS_PATH), exist_ok=True)

        # Initialize embedding model (MUST match what pdf_loader.py uses)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"⚡ Using device: {device.upper()} for embedding")
        embedding_model = get_embedding_model(device=device)

        # Validate documents
        if not documents:
            logger.error("❌ No documents provided to build vector store")
            return False

        logger.info(f"🧠 Building FAISS vector store from {len(documents)} documents...")
        
        # Create FAISS index directly from Document list
        vectorstore = FAISS.from_documents(documents, embedding_model)

        # Save locally
        vectorstore.save_local(DB_FAISS_PATH)
        logger.info(f"✅ Vector store successfully saved to {DB_FAISS_PATH}")

        # Clean up memory
        del vectorstore, embedding_model
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

        return True

    except Exception as e:
        logger.error(f"❌ Failed to build/save vector store: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def load_vector_store() -> Optional[FAISS]:
    """
    Load the FAISS vector store from disk.
    Used by chat_orchestrator to initialize retriever.
    Returns FAISS object or None if not found or corrupted.
    """
    try:
        # Check if index directory exists
        if not os.path.exists(DB_FAISS_PATH):
            logger.warning(f"⚠️ Vector store directory not found: {DB_FAISS_PATH}")
            logger.info("👉 Run 'python app/components/pdf_loader.py' to generate the index first.")
            return None

        # Check for required index files
        required_files = ["index.faiss", "index.pkl"]
        missing = [f for f in required_files if not os.path.exists(os.path.join(DB_FAISS_PATH, f))]
        if missing:
            logger.warning(f"⚠️ Missing FAISS index files: {missing}")
            logger.info("👉 Run 'python app/components/pdf_loader.py' to regenerate the index.")
            return None

        # Initialize embedding model (MUST match what was used during saving)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"⚡ Loading vector store on device: {device.upper()}")
        embedding_model = get_embedding_model(device=device)

        # Load the vector store
        logger.info(f"🔄 Loading FAISS vector store from {DB_FAISS_PATH}...")
        vectorstore = FAISS.load_local(
            DB_FAISS_PATH,
            embedding_model,
            allow_dangerous_deserialization=True  # Required for security context
        )

        logger.info(f"✅ Vector store loaded successfully with {vectorstore.index.ntotal} vectors")
        return vectorstore

    except Exception as e:
        logger.error(f"❌ Failed to load vector store: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None