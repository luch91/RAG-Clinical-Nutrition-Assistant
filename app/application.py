import os
import json
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from app.components.chat_orchestrator import ChatOrchestrator
from app.components.hybrid_retriever import init_retriever
from app.components.vector_store import load_vector_store
from app.common.logger import get_logger
from app.config.config import (
    DEBUG, 
    PORT, 
    CORS_ORIGINS, 
    MAX_CONTENT_LENGTH,
    FLASK_SECRET_KEY,
    DB_FAISS_PATH,
    LOG_FILE
)
import logging

logger = get_logger(__name__)

app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS, supports_credentials=True)

# Configure app security and settings
app.config.update(
    DEBUG=DEBUG,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SECRET_KEY=FLASK_SECRET_KEY,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    JSON_SORT_KEYS=False
)

# Initialize logging
if LOG_FILE:
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    app.logger.addHandler(handler)
    logger.addHandler(handler)

# FIXED: Error recovery for missing FAISS index with graceful degradation
vector_store_available = False
try:
    logger.info("Attempting to load vector store...")
    vector_store = load_vector_store()
    if vector_store:
        init_retriever(vector_store)
        vector_store_available = True
        logger.info("✅ Vector store loaded successfully")
    else:
        logger.warning("⚠️ Vector store not found. Running in FALLBACK MODE (no RAG retrieval).")
        logger.warning("⚠️ System will use LLM-only responses without FCT data.")
except FileNotFoundError as e:
    logger.error(f"❌ Vector store files not found: {str(e)}")
    logger.warning("⚠️ Running in FALLBACK MODE - RAG features disabled")
    logger.warning(f"⚠️ Expected location: {DB_FAISS_PATH}")
    logger.warning("⚠️ Run data indexing script to enable RAG features")
except Exception as e:
    logger.error(f"❌ Failed to load vector store: {str(e)}")
    logger.warning("⚠️ Running in FALLBACK MODE - RAG features disabled")
    import traceback
    logger.error(f"Full traceback: {traceback.format_exc()}")

# Store global flag for health checks
app.config['VECTOR_STORE_AVAILABLE'] = vector_store_available

# Initialize chat orchestrator (works with or without vector store)
chat_orchestrator = ChatOrchestrator()

# Error handler for 404
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

# Error handler for 400
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "message": str(e)}), 400

# Error handler for 500
@app.errorhandler(500)
def internal_error(e):
    logger.exception("Internal server error")
    return jsonify({
        "error": "Internal server error",
        "message": "An unexpected error occurred. Please try again later."
    }), 500

# FIXED: Enhanced health check with external API status
@app.route('/health', methods=['GET'])
def health_check():
    from app.common.circuit_breaker import CircuitBreakers

    # Check external APIs via circuit breakers
    together_status = "unknown"
    hf_status = "unknown"
    rxnorm_status = "unknown"

    try:
        together_breaker = CircuitBreakers.get_breaker("together_api")
        together_status = together_breaker.get_status()["state"]
    except Exception:
        pass

    try:
        hf_breaker = CircuitBreakers.get_breaker("huggingface_api")
        hf_status = hf_breaker.get_status()["state"]
    except Exception:
        pass

    try:
        rxnorm_breaker = CircuitBreakers.get_breaker("rxnorm_api")
        rxnorm_status = rxnorm_breaker.get_status()["state"]
    except Exception:
        pass

    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "components": {
            "vector_store": vector_store_available,
            "together_api": together_status,
            "huggingface_api": hf_status,
            "rxnorm_api": rxnorm_status
        },
        "model_used": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free",
        "degraded_mode": not vector_store_available
    }), 200

# Main chat endpoint
@app.route('/chat', methods=['POST'])
def chat():
    try:
        # Validate request
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
            
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"error": "Invalid JSON: 'query' field required"}), 400
            
        query = data.get('query', '').strip()
        if not query:
            return jsonify({"error": "Empty query"}), 400
            
        # Process the query through the orchestrator
        response = chat_orchestrator.handle_query(query)
        
        # CRITICAL: Ensure medical disclaimer is present
        disclaimer = "For educational purposes only. Not medical advice. Consult a healthcare provider."
        if disclaimer not in response.get('answer', ''):
            if isinstance(response['answer'], str):
                response['answer'] = f"{disclaimer}\n{response.get('answer', '')}"
            else:
                response['answer'] = f"{disclaimer}\n{str(response.get('answer', ''))}"
        
        # Ensure model transparency
        if not response.get('model_note'):
            model_name = response.get('model_used', 'unknown')
            response['model_note'] = f"Using {model_name} model"
        
        # Add session ID for tracking
        response['session_id'] = hash(json.dumps(response))
        
        # Clean up any sensitive debug info before returning
        if 'warnings' in response:
            response['safety_warnings'] = response['warnings']
            del response['warnings']
            
        return jsonify(response)
    
    except Exception as e:
        logger.exception("Chat endpoint error")
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred. Please try again later.",
            "error_type": type(e).__name__
        }), 500

# Reset session endpoint
@app.route('/reset', methods=['POST'])
def reset_session():
    try:
        chat_orchestrator.reset_session()
        return jsonify({
            "message": "Session reset successfully",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        logger.exception("Reset session error")
        return jsonify({
            "error": "Failed to reset session",
            "message": str(e)
        }), 500

# Serve static files (for UI if needed)
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# Start the server
if __name__ == '__main__':
    logger.info(f"Starting Clinical Nutrition Assistant on port {PORT}")
    logger.info(f"Vector store path: {DB_FAISS_PATH}")
    logger.info(f"Model strategy: {os.getenv('DEFAULT_MODEL_STRATEGY', 'therapy')}")
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)