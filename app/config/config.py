# app/config/config.py
import os
from dotenv import load_dotenv

# ====================================================
# Load Environment Variables - MUST BE FIRST
# ====================================================
load_dotenv()

# ====================================================
# API KEYS - MUST BE DEFINED AT MODULE LEVEL
# ====================================================
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")

# ====================================================
# API Configuration - MUST BE DEFINED AT MODULE LEVEL
# ====================================================
API_TIMEOUT = int(os.getenv("API_TIMEOUT", 60))  # default 60 seconds
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))   # default 3 attempts
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 5))   # default 5 seconds
DEFAULT_MODEL_STRATEGY = os.getenv("DEFAULT_MODEL_STRATEGY", "therapy")  # defaults to therapy for safety
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 5000))  # Added missing PORT variable
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")  # Added missing CORS_ORIGINS
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 10485760))  # 10MB
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "your-secret-key-here")
LOG_FILE = os.getenv("LOG_FILE", None)

# ====================================================
# Medication Validation Configuration
# ====================================================
ENABLE_MEDICATION_VALIDATION = os.getenv("ENABLE_MEDICATION_VALIDATION", "true").lower() == "true"
MEDICATION_API_TIMEOUT = int(os.getenv("MEDICATION_API_TIMEOUT", 5))  # seconds
MEDICATION_VALIDATION_CONFIDENCE = float(os.getenv("MEDICATION_CONFIDENCE", 0.75))  # 75% confidence threshold

# ====================================================
# Paths - Will be initialized on demand
# ====================================================
BASE_DIR = None
APP_DIR = None
CONFIG_DIR = None
DATA_PATH = None
MODELS_PATH = None
DB_FAISS_PATH = None
DISTILBERT_CLASSIFIER_PATH = None
CHUNKS_CACHE_PATH = None
CHUNK_SIZE = None
CHUNK_OVERLAP = None
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # Used by pdf_loader and vector_store

def initialize_paths(project_root=None):
    """Initialize all paths based on the project root"""
    global BASE_DIR, APP_DIR, CONFIG_DIR, DATA_PATH, MODELS_PATH, DB_FAISS_PATH
    global DISTILBERT_CLASSIFIER_PATH, CHUNKS_CACHE_PATH, CHUNK_SIZE, CHUNK_OVERLAP
    
    # Use provided project root or determine it
    if project_root is None:
        # __file__ points to .../NUTRITION RAG CHATBOT/app/config/config.py
        CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
        APP_DIR = os.path.dirname(CONFIG_DIR)
        BASE_DIR = os.path.dirname(APP_DIR)
    else:
        BASE_DIR = os.path.abspath(project_root)
        APP_DIR = os.path.join(BASE_DIR, 'app')
        CONFIG_DIR = os.path.join(APP_DIR, 'config')
    
    # Set other paths
    DATA_PATH = os.path.join(BASE_DIR, "data")
    CHUNKS_CACHE_PATH = os.path.join(os.path.dirname(DATA_PATH), "cache", "chunks.pkl")

    # FIXED: Use environment variable or relative path instead of hardcoded absolute path
    MODELS_PATH = os.getenv(
        "MODELS_PATH",
        os.path.join(BASE_DIR, "machine_learning", "models")
    )
    DB_FAISS_PATH = os.getenv("DB_FAISS_PATH", os.path.join(BASE_DIR, "vectorstore", "db_faiss"))

    # DistilBERT Classifier
    DISTILBERT_CLASSIFIER_PATH = os.getenv(
        "DISTILBERT_CLASSIFIER_PATH",
        os.path.join(MODELS_PATH, "distilbert-clinical-v2")
    )
    
    # Print for debugging
    print("\n=== PATH DEBUGGING ===")
    print(f"Current working directory: {os.getcwd()}")
    print(f"PROJECT_ROOT: {BASE_DIR}")
    print(f"MODELS_PATH: {MODELS_PATH}")
    print(f"Does MODELS_PATH exist? {os.path.exists(MODELS_PATH)}")
    if os.path.exists(MODELS_PATH):
        print(f"Contents of MODELS_PATH: {os.listdir(MODELS_PATH)}")
    
    print(f"DISTILBERT_CLASSIFIER_PATH: {DISTILBERT_CLASSIFIER_PATH}")
    print(f"Does classifier path exist? {os.path.exists(DISTILBERT_CLASSIFIER_PATH)}")
    if os.path.exists(DISTILBERT_CLASSIFIER_PATH):
        print(f"Contents of classifier directory: {os.listdir(DISTILBERT_CLASSIFIER_PATH)}")
    
    print(f"CHUNKS_CACHE_PATH: {CHUNKS_CACHE_PATH}")
    print(f"Does chunks cache exist? {os.path.exists(CHUNKS_CACHE_PATH)}")
    
    print(f"DB_FAISS_PATH: {DB_FAISS_PATH}")
    print(f"Does FAISS index dir exist? {os.path.exists(DB_FAISS_PATH)}")
    if os.path.exists(DB_FAISS_PATH):
        print(f"FAISS contents: {os.listdir(DB_FAISS_PATH)}")
    
    # Chunking parameters
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 100))

# ====================================================
# Model Config Helper — DEPRECATED / UNUSED
# ====================================================
# We do NOT use any Hugging Face model via API URL anymore.
# All LLM routing is handled by api_models.py using gemma-2b and deepseek.
# This function is kept only for backward compatibility — but its values are ignored.
def get_model_config(model_name: str):
    """
    Return configuration for supported models.
    This function is deprecated — model selection is now handled entirely by api_models.py.
    """
    # Return dummy values — they are not used in production
    return {
        "path": None,
        "type": "generic",
        "api_url": ""
    }

# Initialize paths on import
initialize_paths()