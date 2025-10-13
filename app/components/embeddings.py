from langchain_huggingface import HuggingFaceEmbeddings
from app.common.logger import get_logger
from app.common.custom_exception import CustomException

logger = get_logger(__name__)

def get_embedding_model(
    model_name: str = "pritamdeka/S-PubMedBert-MS-MARCO",  # Clinical focus
    device: str = "cpu"
):
    """
    Clinical Pediatric Nutrition embedding model.
    Optimized for medical terminology and clinical text retrieval.
    """
    try:
        logger.info(f"Initializing clinical embedding model: {model_name} on {device}")

        model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True}
        )

        logger.info("✅ Clinical embedding model loaded successfully")
        return model

    except Exception as e:
        # Fallback chain
        fallbacks = [
            "pritamdeka/Sentence-BERT-msmarco-calculative-passage",
            "sentence-transformers/all-MiniLM-L6-v2"
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
            except:
                continue
                
        logger.error("All embedding models failed")
        raise e