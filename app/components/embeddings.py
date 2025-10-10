from langchain_huggingface import HuggingFaceEmbeddings
from app.common.logger import get_logger
from app.common.custom_exception import CustomException

logger = get_logger(__name__)

def get_embedding_model(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    device: str = "cpu"
):
    """
    Initialize HuggingFace embedding model with optional device parameter.
    
    Args:
        model_name: Name of HuggingFace model to load
        device: "cpu" or "cuda"
    """
    try:
        logger.info(f"Initializing HuggingFace embedding model: {model_name} on {device}")

        model = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device}
        )

        logger.info("✅ HuggingFace embedding model loaded successfully")
        return model

    except Exception as e:
        error_message = CustomException(
            f"Error occurred while loading embedding model {model_name} on {device}", e
        )
        logger.error(str(error_message))
        raise error_message
