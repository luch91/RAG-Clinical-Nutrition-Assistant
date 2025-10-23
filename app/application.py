# app/application.py
import os
import uuid
import json
import logging
import datetime
from pathlib import Path
from typing import Dict, Any
from flask import Flask, request, jsonify, send_from_directory

from app.common.logger import get_logger
from app.common.custom_exception import CustomException
from app.components.llm_response_manager import LLMResponseManager
from app.components.hybrid_retriever import init_retriever, _retriever_manager
from app.components.vector_store import load_vector_store

logger = get_logger(__name__)

# Flask app
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = Path("user_uploads")
app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)

# Instantiate core managers
llm = LLMResponseManager(dri_table_path="data/dri_table.csv")

# Try to initialize retrieval (FAISS + BM25). Tolerate failures and continue.
vector_store_available = False
try:
    logger.info("Attempting to load vector store...")
    vector_store = load_vector_store()
    if vector_store:
        init_retriever(vector_store)
        vector_store_available = True
        logger.info("✅ Vector store and retriever initialized successfully")
    else:
        logger.warning("⚠️ Vector store not found. Running in FALLBACK MODE (no RAG retrieval)")
except FileNotFoundError as e:
    logger.error(f"❌ Vector store files not found: {str(e)}")
    logger.warning("⚠️ Running in FALLBACK MODE - RAG features disabled")
except Exception as e:
    logger.error(f"❌ Failed to load vector store: {str(e)}")
    logger.warning("⚠️ Running in FALLBACK MODE - RAG features disabled")

# Health and uptime
START_TIME = datetime.datetime.utcnow()

# -------------------------
# Utilities
# -------------------------
def _get_session(session_id: str) -> Dict[str, Any]:
    if not session_id:
        session_id = str(uuid.uuid4())
    # LLMResponseManager keeps sessions in-memory; expose it
    return llm._get_session(session_id), session_id

def _safe_jsonify(obj):
    try:
        return jsonify(obj)
    except TypeError:
        return jsonify({"error": "Non-serializable response", "repr": str(obj)})

# -------------------------
# Endpoints
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    uptime = (datetime.datetime.utcnow() - START_TIME).total_seconds()
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(uptime),
        "vector_store_available": _retriever_manager.is_available(),
        "timestamp": datetime.datetime.utcnow().isoformat()
    })

@app.route("/chat", methods=["POST"])
def chat():
    """
    Expects JSON: {"session_id": <str optional>, "query": <str>}
    Returns: {"response": <LLM manager response dict>, "session_id": <id>, "profile": {...}}
    """
    try:
        if not request.is_json:
            return jsonify({"error": "request must be application/json"}), 415
        payload = request.get_json()
        session_id = payload.get("session_id") or str(uuid.uuid4())
        query = payload.get("query", "")
        if not query:
            return jsonify({"error": "query field required"}), 400

        # Ensure session exists
        llm._get_session(session_id)

        # Call LLMResponseManager — this performs classification -> retrieval -> generation pipeline
        response = llm.handle_user_query(session_id, query)

        # Also return a lightweight profile snapshot for UI
        sess = llm._get_session(session_id)
        profile = {
            "name": sess["slots"].get("name"),
            "age": sess["slots"].get("age"),
            "height": sess["slots"].get("height_cm"),
            "weight": sess["slots"].get("weight_kg"),
            "diagnosis": sess["slots"].get("diagnosis"),
            "therapy_area": sess["slots"].get("therapy_area"),
            "biomarkers": sess.get("lab_results") or sess.get("slots", {}).get("biomarkers_detailed", {})
        }

        out = {"response": response, "session_id": session_id, "profile": profile}
        return jsonify(out)
    except Exception as e:
        logger.exception("Chat endpoint error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload():
    """
    Multipart upload: form fields: session_id (optional). file under 'file'
    Saves to user_uploads/ and records path in session slots uploaded_lab_file.
    """
    try:
        session_id = request.form.get("session_id") or request.args.get("session_id") or str(uuid.uuid4())
        if "file" not in request.files:
            return jsonify({"error": "no file part"}), 400
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"error": "empty filename"}), 400

        # sanitize and save
        filename = f"{session_id}{uuid.uuid4().hex}{Path(f.filename).name}"
        save_path = app.config["UPLOAD_FOLDER"] / filename
        f.save(save_path)

        # record in session slots
        sess = llm._get_session(session_id)
        sess["slots"]["uploaded_lab_file"] = str(save_path)

        logger.info("Saved upload %s for session %s", save_path, session_id)
        return jsonify({"ok": True, "message": f"Uploaded {filename}", "session_id": session_id})
    except Exception as e:
        logger.exception("Upload error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/parse_labs", methods=["POST"])
def parse_labs():
    """
    Placeholder lab parser. In production replace with OCR + regex mapping.
    Expects JSON {"session_id": <id>}
    Returns {"extracted": {biomarker: {"value":..,"unit":..}}, "session_id":...}
    """
    try:
        payload = request.get_json() or {}
        session_id = payload.get("session_id") or request.args.get("session_id")
        if not session_id:
            return jsonify({"error": "session_id required"}), 400

        sess = llm._get_session(session_id)

        # find uploaded file
        uploaded = sess["slots"].get("uploaded_lab_file")
        if not uploaded:
            return jsonify({"error": "no uploaded lab file for session"}), 400

        # === Placeholder extraction: simulate parsing ===
        # Replace this block with your OCR pipeline (eg. Tesseract or Vision API) + regex extraction
        # We'll pretend we extracted HbA1c and glucose for demonstration
        extracted = {
            "HbA1c": {"value": 8.5, "unit": "%"},
            "glucose": {"value": 150, "unit": "mg/dL"}
        }

        # update session slots
        sess.setdefault("slots", {})
        sess.setdefault("slots", {}).setdefault("biomarkers_detailed", {})
        for k, v in extracted.items():
            sess["slots"]["biomarkers_detailed"][k.lower()] = {"value": v["value"], "unit": v["unit"], "raw": f"{k} {v['value']}{v['unit']}"}

        # Also append to parsed lab_results for LLMResponseManager convenience
        sess.setdefault("lab_results", [])
        sess["lab_results"].append(extracted)

        logger.info("Parsed labs for session %s -> %s", session_id, list(extracted.keys()))
        return jsonify({"extracted": extracted, "session_id": session_id})
    except Exception as e:
        logger.exception("parse_labs error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/mealplan", methods=["POST"])
def mealplan():
    """
    Generate 3-day meal plan.
    Accepts JSON {session_id, accept: bool}
    Returns {"result": <manager result>}
    """
    try:
        payload = request.get_json() or {}
        session_id = payload.get("session_id")
        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        accept = bool(payload.get("accept", False))

        # call into LLMResponseManager
        result = llm.request_3day_meal_plan(session_id, accept=accept)
        return jsonify({"result": result, "session_id": session_id})
    except Exception as e:
        logger.exception("mealplan error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/profile", methods=["GET"])
def profile():
    """
    Return a lightweight profile summary for a session: ?session_id=...
    """
    try:
        session_id = request.args.get("session_id")
        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        sess = llm._get_session(session_id)
        profile = {
            "name": sess["slots"].get("name"),
            "age": sess["slots"].get("age"),
            "height": sess["slots"].get("height_cm"),
            "weight": sess["slots"].get("weight_kg"),
            "diagnosis": sess["slots"].get("diagnosis"),
            "therapy_area": sess["slots"].get("therapy_area"),
            "biomarkers": sess.get("lab_results") or sess.get("slots", {}).get("biomarkers_detailed", {})
        }
        return jsonify({"profile": profile, "session_id": session_id})
    except Exception as e:
        logger.exception("profile error: %s", e)
        return jsonify({"error": str(e)}), 500

# Static file serving helper (optional) for uploads
@app.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    try:
        return send_from_directory(str(app.config["UPLOAD_FOLDER"]), filename, as_attachment=False)
    except Exception as e:
        logger.exception("serve_upload error: %s", e)
        return jsonify({"error": str(e)}), 404

# -------------------------
# Run as script
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Starting Clinical Nutrition Assistant Flask Backend on port {port}")
    logger.info(f"Vector store available: {vector_store_available}")
    logger.info(f"Retriever available: {_retriever_manager.is_available()}")
    logger.info(f"Access the API at: http://127.0.0.1:{port}")
    logger.info(f"Health check: http://127.0.0.1:{port}/health")
    app.run(host="127.0.0.1", port=port, debug=False)