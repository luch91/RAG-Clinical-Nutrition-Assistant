from langchain_huggingface import HuggingFaceEmbeddings
from app.common.logger import get_logger
from app.common.custom_exception import CustomException

logger = get_logger(__name__)

def get_embedding_model(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",  # Reliable, fast baseline
    device: str = "cpu"
):
    """
    Clinical Pediatric Nutrition embedding model.

    Model Selection Strategy:
    1. Primary: all-MiniLM-L6-v2 - Fast, reliable, good general performance
    2. Fallback 1: multi-qa-MiniLM-L6-cos-v1 - Q&A optimized
    3. Fallback 2: paraphrase-MiniLM-L6-v2 - Semantic similarity

    Note: Medical-specific models (PubMedBERT variants) often fail to load properly
    or lack proper sentence-transformers configuration. The MiniLM models provide
    robust performance across medical and general domains.
    """
    try:
        logger.info(f"Initializing embedding model: {model_name} on {device}")

        model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True}
        )

        logger.info(f"✅ Embedding model loaded successfully: {model_name}")
        return model

    except Exception as e:
        # Fallback chain with proven models
        fallbacks = [
            "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",  # Q&A optimized
            "sentence-transformers/paraphrase-MiniLM-L6-v2"     # Semantic similarity
        ]

        for fallback_model in fallbacks:
            try:
                logger.warning(f"⚠️ Primary model failed, trying: {fallback_model}")
                model = HuggingFaceEmbeddings(
                    model_name=fallback_model,
                    model_kwargs={"device": device},
                    encode_kwargs={"normalize_embeddings": True}
                )
                logger.info(f"✅ Fallback model loaded: {fallback_model}")
                return model
            except Exception as fallback_error:
                logger.warning(f"Fallback {fallback_model} failed: {str(fallback_error)}")
                continue

        logger.error("❌ All embedding models failed to load")
        raise CustomException(f"Failed to load any embedding model. Last error: {str(e)}", e)
