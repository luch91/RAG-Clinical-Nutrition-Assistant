# app/routes/chat.py
from flask import Blueprint, request, jsonify
from app.components.chat_orchestrator import ChatOrchestrator
from app.common.logger import get_logger

bp = Blueprint("chat", __name__)
logger = get_logger(__name__)

# Persist orchestrator across requests to maintain conversation state
_ORCHESTRATOR = ChatOrchestrator()

@bp.route("/api/chat", methods=["POST"])
def chat():
    """
    Body:
      {
        "query": "text",
        "profile": {
          "age": 34, "sex": "female", "weight_kg": 62, "height_cm": 168,
          "country": "Nigeria_2019",
          "diagnosis": "eczema",
          "allergies": ["maize"],
          "medications": ["metformin"]
        },
        "file_text": "optional uploaded text content"
      }
    """
    try:
        data = request.get_json(force=True)
        query = (data.get("query") or "").strip()
        file_text = (data.get("file_text") or "").strip()
        profile = data.get("profile") or {}

        if file_text:
            # Simple, explicit composition; Orchestrator still runs Ambiguity Gate if needed.
            query = f"{query}\n\n[Uploaded Context]\n{file_text}"

        # Pre-fill session with profile-ish info (won’t override user-provided per Orchestrator logic)
        _ORCHESTRATOR.session_slots.update({k: v for k, v in (profile or {}).items() if v is not None})

        result = _ORCHESTRATOR.handle_query(query)

        response = {
            "template": result.get("template"),
            "answer": result.get("answer"),
            "model_used": result.get("model_used"),
            "llm_model_id": result.get("llm_model_id"),
            "therapy_output": result.get("therapy_output"),
            "therapy_summary": result.get("therapy_summary"),
            "sources": result.get("sources_used", []),
            "citations": result.get("citations", []),
            "profile_echo": _ORCHESTRATOR.session_slots,
            # Optional polish fields used by the UI for transparency and UX hints
            "model_note": result.get("model_note"),
            "warnings": result.get("warnings", []),
            "disclaimer": "NutriIntel is for learning and educational purposes only and does not replace professional medical advice."
        }
        return jsonify(response)
    except Exception as e:
        logger.error(f"/api/chat failed: {e}")
        return jsonify({"error": "Chat failed", "detail": str(e)}), 500
