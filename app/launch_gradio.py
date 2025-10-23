# launch_gradio.py
"""
Gradio UI for NutriNest — Pediatric Clinical Nutrition Assistant
Requirements:
- Flask backend running (see BACKEND_URL)
- Endpoints expected (best-effort, will fallback if missing):
    POST /chat            -> accepts {"session_id","query"} returns response dict
    POST /upload          -> accepts multipart file + session_id -> {"ok":True,"message":...}
    POST /parse_labs      -> accepts {"session_id"} -> {"extracted": {...}}
    POST /mealplan        -> accepts {"session_id","accept": True} -> {"result": {...}}
    GET  /profile         -> accepts ?session_id=... -> {"profile": {...}}
If endpoints are missing the UI will still operate locally but without server-backed persistence.
"""

import os
import uuid
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import requests
import gradio as gr
from app.common.logger import get_logger

logger = get_logger(__name__)

# -------------------------
# Config
# -------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000")  # Run flask app first
TIMEOUT = 25

# App identity
APP_NAME = "NutriNest"
TAGLINE = "NutriNest 🪶 — Nurturing clinical nutrition with intelligence."

# Exact required welcome message (verbatim content as requested)
WELCOME_MESSAGE = (
    "I provide evidence-based nutrition guidance for pediatric patients (0-18 years).\n\n"
    "I can help with:\n\n"
    "🔹 Food Comparisons\n"
    "Example: \"Compare boiled maize vs fermented maize for a 6-month-old\"\n\n"
    "🔹 General Nutrition Questions\n"
    "Example: \"What foods are high in iron for toddlers?\"\n\n"
    "🔹 Dietary Recommendations (diagnosis-based)\n"
    "Example: \"My 8-year-old has type 1 diabetes, what should they eat?\"\n\n"
    "🔹 Clinical Therapy Plans (biomarker-driven nutrition therapy)\n"
    "Supported conditions:\n"
    "• Preterm Nutrition\n"
    "• Type 1 Diabetes\n"
    "• Food Allergy\n"
    "• Cystic Fibrosis\n"
    "• Inherited Metabolic Disorders (PKU, MSUD, Galactosemia)\n"
    "• Epilepsy / Ketogenic Therapy\n"
    "• Chronic Kidney Disease\n"
    "• GI Disorders (IBD / GERD)\n\n"
    "Example: \"10yo with type 1 diabetes, HbA1c 8.5%, glucose 150 mg/dL. Need meal plan.\"\n\n"
    "Getting Started:\n"
    "• For therapy plans: Provide diagnosis, age, weight, height, and biomarkers\n"
    "• For food comparisons: Specify age and preparation method\n"
    "• All recommendations are evidence-based with clinical citations\n\n"
    "What would you like to know today?\n\n"
    "---\n\n"
    "⚠ For educational purposes only. Not medical advice. Consult a healthcare provider."
)

# Therapy-only nudge (text-only per your request; will be inserted when therapy follow-ups missing)
THERAPY_NUDGE_TEMPLATE = (
    "How would you like to proceed?\n\n"
    "📋 Option 1: Upload Lab Results (Fastest)\n"
    "   Upload a PDF or photo of recent lab report. I'll extract biomarker values automatically.\n\n"
    "✍ Option 2: Answer Step-by-Step ({num_missing} questions)\n"
    "   I'll ask one question at a time (age, medications, labs, etc.).\n\n"
    "📚 Option 3: General {diag_or_diet} Information First\n"
    "   Get general diet guidelines for {diag_or_diet} while you gather clinical data.\n\n"
    "Which option works best for you? (Type 'upload labs', 'step by step', or 'general info first')\n\n"
    "⚠ For educational purposes only. Not medical advice. Consult a healthcare provider."
)

# -------------------------
# Local UI session state
# -------------------------
_histories: Dict[str, List[Dict[str, str]]] = {}  # session_id -> list of messages {sender,text}
_local_profiles: Dict[str, Dict[str, Any]] = {}   # session_id -> profile dict

# -------------------------
# HTTP helpers
# -------------------------
def _post(path: str, json_payload: Dict = None, files=None, timeout: int = TIMEOUT) -> Dict:
    url = f"{BACKEND_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        if files:
            r = requests.post(url, data=json_payload or {}, files=files, timeout=timeout)
        else:
            r = requests.post(url, json=json_payload or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug("POST error %s -> %s", url, e)
        return {"_error": str(e)}

def _get(path: str, params: Dict = None, timeout: int = TIMEOUT) -> Dict:
    url = f"{BACKEND_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug("GET error %s -> %s", url, e)
        return {"_error": str(e)}

# -------------------------
# History helpers
# -------------------------
def new_session_id() -> str:
    return str(uuid.uuid4())

def append_message(session_id: str, sender: str, text: str):
    _histories.setdefault(session_id, []).append({"sender": sender, "text": text})

def get_chat_history_for_gradio(session_id: str) -> List[Tuple[str, str]]:
    hist = _histories.get(session_id, [])
    # produce list of (user, bot) pairs per Gradio Chatbot expectations
    conv = []
    pending_user = None
    for m in hist:
        if m["sender"] == "user":
            pending_user = m["text"]
        else:
            bot_text = m["text"]
            if pending_user is None:
                # system or bot message without preceding user -> show as bot-only
                conv.append(("NutriNest", bot_text))
            else:
                conv.append((pending_user, bot_text))
                pending_user = None
    if pending_user:
        conv.append((pending_user, ""))  # user message waiting for reply
    return conv

# -------------------------
# Profile helpers
# -------------------------
def fetch_profile_from_backend(session_id: str) -> Dict[str, Any]:
    resp = _get("/profile", params={"session_id": session_id})
    if resp.get("_error"):
        # backend not available or endpoint missing -> fallback to local
        return _local_profiles.get(session_id, {})
    return resp.get("profile", {}) or {}

def update_local_profile_from_response(session_id: str, response: Dict[str, Any]):
    # heuristics: read payload or session slots in response if present
    # populate local profile for sidebar if backend /profile not implemented
    prof = _local_profiles.setdefault(session_id, {})
    last_query_info = response.get("last_query_info") or response.get("query_info") or {}
    slots = response.get("slots") or {}
    # Try common keys
    prof.setdefault("name", slots.get("name") or prof.get("name", "—"))
    prof.setdefault("age", slots.get("age") or prof.get("age", "—"))
    prof.setdefault("height", slots.get("height_cm") or prof.get("height", "—"))
    prof.setdefault("weight", slots.get("weight_kg") or prof.get("weight", "—"))
    prof.setdefault("diagnosis", slots.get("diagnosis") or prof.get("diagnosis", "—"))
    biomarkers = slots.get("biomarkers_detailed") or prof.get("biomarkers") or {}
    prof.setdefault("biomarkers", biomarkers)
    _local_profiles[session_id] = prof

# -------------------------
# Business logic: send a user message
# -------------------------
def send_message(session_id: str, user_text: str):
    """
    1) Append user message locally
    2) POST to /chat with session_id and query
    3) Interpret response structure and append formatted bot message(s)
    4) Return updated chat + profile fields
    """
    if not session_id:
        session_id = new_session_id()

    append_message(session_id, "user", user_text)

    # call backend /chat
    payload = {"session_id": session_id, "query": user_text}
    resp = _post("/chat", json_payload=payload)

    # handle network error gracefully
    if resp.get("_error"):
        bot_text = f"⚠ Backend error: {resp.get('_error')}\n\nYou can still continue locally."
        append_message(session_id, "bot", bot_text)
        # profile fallback
        profile = fetch_profile_from_backend(session_id)
        return get_chat_history_for_gradio(session_id), profile.get("name","—"), str(profile.get("age","—")), str(profile.get("height","—")), str(profile.get("weight","—")), profile.get("diagnosis","—"), ", ".join(sorted(profile.get("biomarkers", {}).keys())) if profile.get("biomarkers") else "—", session_id

    # The Flask /chat returns a structured response (LLMResponseManager output)
    # In your application.py the function does return jsonify(response) so resp IS the response dict.
    result = resp  # shorthand

    # Update local profile heuristics
    try:
        update_local_profile_from_response(session_id, result)
    except Exception:
        logger.debug("Profile update heuristic failed.")

    # Format assistant output
    bot_segments: List[str] = []

    # If the system returned a 'status' guiding flow:
    status = result.get("status") or (result.get("last_query_info") or {}).get("label")
    if status == "needs_slot":
        # single follow-up question
        followup_text = result.get("followup") or "I need more information. Could you please clarify?"
        # Therapy-specific: if last_query_info.label == "therapy", show therapy nudge text (no buttons)
        last_q = result.get("last_query_info") or {}
        if last_q.get("label") == "therapy":
            # compute missing items count if available
            missing_items = result.get("missing_items") or []
            nudge = THERAPY_NUDGE_TEMPLATE.format(
                num_missing=len(missing_items) if missing_items else 3,
                diag_or_diet=(result.get("diagnosis") or "this condition")
            )
            # present followup + nudge
            bot_segments.append(followup_text)
            bot_segments.append("\n\n" + nudge)
        else:
            bot_segments.append(followup_text)

    elif status == "downgraded":
        # model downgraded therapy -> recommendation + message
        bot_segments.append(result.get("message", "Downgraded to recommendation."))
        # add short preview if recommendation payload included
        rec = result.get("recommendation_payload")
        if rec:
            bot_segments.append("\nPreview:\n" + json.dumps(rec, default=str, indent=2)[:2000])

    elif status in ("therapy_ready",):
        payload = result.get("payload", {}) or {}
        bot_segments.append(payload.get("message", "Therapy targets prepared."))
        # add energy/macros summary if available
        if payload.get("energy_macros"):
            bot_segments.append("\nEnergy & Macros:\n" + json.dumps(payload.get("energy_macros"), indent=2)[:2000])
        bot_segments.append("\nType 'generate 3-day meal plan' to create a plan.")

    elif status == "ok" and result.get("payload"):
        payload = result.get("payload")
        # render per query_type
        qtype = payload.get("query_type")
        if qtype == "recommendation":
            bot_segments.append("Recommendation prepared.\n\nMicronutrient targets:\n")
            bot_segments.append(json.dumps(payload.get("micronutrient_targets", {}), indent=2)[:2000])
            # brief food sources
            fs = payload.get("food_sources", {})
            if fs:
                count_summary = ", ".join([f"{k}: {len(v)}" for k,v in list(fs.items())[:6]])
                bot_segments.append("\nRepresentative food sources (counts): " + count_summary)
        elif qtype == "comparison":
            bot_segments.append(payload.get("summary_text") or "Comparison prepared.")
            bot_segments.append("\nType 'detailed table' to fetch nutrient-by-nutrient values.")
        elif qtype == "general":
            bot_segments.append(payload.get("summary_text") or "Here is the general information you requested.")
            snippets = payload.get("snippets") or []
            if snippets:
                bot_segments.append(f"\nRetrieved {len(snippets)} passages. Use 'show sources' to view citations.")
        else:
            # default fallback
            bot_segments.append(result.get("message") or json.dumps(result.get("payload"), default=str)[:2000])

    else:
        # Unknown structure - show raw
        bot_segments.append(json.dumps(result, default=str, indent=2)[:4000])

    # Always append citations if present
    cites = result.get("citations") or result.get("references") or result.get("sources")
    if cites:
        try:
            # Expect list of dicts or strings
            if isinstance(cites, list):
                cite_texts = []
                for c in cites[:3]:
                    if isinstance(c, dict):
                        # metadata: title, doc, page
                        title = c.get("title") or c.get("source") or c.get("doc") or str(c)
                        page = c.get("page") or c.get("page_number") or ""
                        cite_texts.append(f"{title}{(' — p.'+str(page)) if page else ''}")
                    else:
                        cite_texts.append(str(c))
                bot_segments.append("\nReferences:\n" + "\n".join(cite_texts))
            else:
                bot_segments.append("\nReferences:\n" + str(cites))
        except Exception:
            bot_segments.append("\nReferences available.")

    # LLM transparency
    model_note = result.get("model_note") or result.get("model_used") or result.get("model")
    if model_note:
        bot_segments.append(f"\n(Model used: {model_note})")

    # Add educational disclaimer for clinical/therapy responses
    if (isinstance(status, str) and "therapy" in status) or (result.get("last_query_info", {}).get("label") == "therapy"):
        bot_segments.append("\n⚠ For educational purposes only. Not medical advice. Consult a healthcare provider.")

    full_bot_text = "\n\n".join(bot_segments)
    append_message(session_id, "bot", full_bot_text)

    # Update profile from backend if possible
    profile = fetch_profile_from_backend(session_id)
    if not profile:
        profile = _local_profiles.get(session_id, {})

    # return values for gradio outputs (chat history + profile fields)
    return get_chat_history_for_gradio(session_id), profile.get("name","—"), str(profile.get("age","—")), str(profile.get("height","—")), str(profile.get("weight","—")), profile.get("diagnosis","—"), ", ".join(sorted(profile.get("biomarkers", {}).keys())) if profile.get("biomarkers") else "—", session_id

# -------------------------
# Upload handler
# -------------------------
def upload_file(session_id: str, file_obj):
    """
    file_obj is a Gradio temporary file object; will upload to backend /upload
    """
    if not session_id:
        session_id = new_session_id()
    if not file_obj:
        append_message(session_id, "bot", "No file selected.")
        return get_chat_history_for_gradio(session_id), session_id

    # Prepare file for requests
    try:
        fpath = file_obj.name
        with open(fpath, "rb") as fh:
            files = {"file": (Path(fpath).name, fh, "application/octet-stream")}
            payload = {"session_id": session_id}
            resp = _post("/upload", json_payload=payload, files=files)
    except Exception as e:
        logger.exception("Upload failed: %s", e)
        append_message(session_id, "bot", f"Upload error: {e}")
        return get_chat_history_for_gradio(session_id), session_id

    if resp.get("_error"):
        append_message(session_id, "bot", f"Upload failed: {resp.get('_error')}")
    else:
        msg = resp.get("message") or resp.get("ok") and "Uploaded successfully." or "Upload succeeded."
        append_message(session_id, "bot", f"✅ {msg}\nType 'parse labs' to extract biomarkers or wait for automatic parsing.")
    return get_chat_history_for_gradio(session_id), session_id

# -------------------------
# Parse labs handler
# -------------------------
def parse_labs(session_id: str):
    if not session_id:
        session_id = new_session_id()
    resp = _post("/parse_labs", json_payload={"session_id": session_id})
    if resp.get("_error"):
        append_message(session_id, "bot", f"Parse labs failed: {resp.get('_error')}")
        return get_chat_history_for_gradio(session_id), session_id, "—", "—", "—", "—", "—", "—"
    extracted = resp.get("extracted") or {}
    # update local profile
    prof = _local_profiles.setdefault(session_id, {})
    prof.setdefault("biomarkers", {})
    for k,v in extracted.items():
        prof["biomarkers"][k] = v
    append_message(session_id, "bot", f"Parsed labs and extracted: {', '.join(extracted.keys())}")
    profile = fetch_profile_from_backend(session_id) or prof
    return get_chat_history_for_gradio(session_id), session_id, profile.get("name","—"), str(profile.get("age","—")), str(profile.get("height","—")), str(profile.get("weight","—")), profile.get("diagnosis","—"), ", ".join(sorted(profile.get("biomarkers", {}).keys())) if profile.get("biomarkers") else "—"

# -------------------------
# Meal plan handler
# -------------------------
def request_mealplan(session_id: str):
    if not session_id:
        session_id = new_session_id()
    resp = _post("/mealplan", json_payload={"session_id": session_id, "accept": True})
    if resp.get("_error"):
        append_message(session_id, "bot", f"Meal plan generation failed: {resp.get('_error')}")
        return get_chat_history_for_gradio(session_id), session_id, "—", "—", "—", "—", "—", "—"
    result = resp.get("result") or resp
    append_message(session_id, "bot", "✅ Generated 3-day meal plan. See summary below.")
    append_message(session_id, "bot", json.dumps(result.get("meal_plan", result), indent=2)[:4000])
    profile = fetch_profile_from_backend(session_id)
    return get_chat_history_for_gradio(session_id), session_id, profile.get("name","—"), str(profile.get("age","—")), str(profile.get("height","—")), str(profile.get("weight","—")), profile.get("diagnosis","—"), ", ".join(sorted(profile.get("biomarkers", {}).keys())) if profile.get("biomarkers") else "—"

# -------------------------
# Gradio UI layout
# -------------------------
def build_ui():
    with gr.Blocks(title=f"{APP_NAME} — Pediatric Nutrition Assistant") as ui:
        gr.Markdown(f"## {APP_NAME}  {TAGLINE}")
        gr.Markdown("For educational purposes only. Not medical advice. Consult a healthcare professional.")

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(label="Chat with NutriNest", elem_id="nutrinest_chat", height=600)
                user_input = gr.Textbox(placeholder="Type your question here (e.g., 'Compare boiled maize vs fermented maize for a 6-month-old')", lines=2)
                with gr.Row():
                    send_btn = gr.Button("Send")
                    upload = gr.File(label="Upload lab report (PDF / IMG)", file_types=[".pdf", ".png", ".jpg", ".jpeg"])
                    parse_btn = gr.Button("Parse labs (after upload)")
                    mealplan_btn = gr.Button("Generate 3-day meal plan")
                session_state = gr.State(new_session_id())

            with gr.Column(scale=1):
                gr.Markdown("### Patient profile (auto-filled)")
                name_field = gr.Textbox(label="Name", value="—", interactive=False)
                age_field = gr.Textbox(label="Age", value="—", interactive=False)
                height_field = gr.Textbox(label="Height (cm)", value="—", interactive=False)
                weight_field = gr.Textbox(label="Weight (kg)", value="—", interactive=False)
                diagnosis_field = gr.Textbox(label="Diagnosis", value="—", interactive=False)
                biomarkers_field = gr.Textbox(label="Biomarkers (parsed)", value="—", interactive=False)
                model_field = gr.Textbox(label="Model used (transparency)", value="—", interactive=False)
                gr.Markdown("### Nudges / Next steps\n(typed commands only — no buttons)\n\n• upload labs — to upload PDF or photo\n\n• step by step — answer one question at a time\n\n• general info first — get general guidance before clinical data")

        # Initialize: show welcome message (one-time per session)
        def init(session_id):
            if not session_id:
                session_id = new_session_id()
            # prime history and profile
            _histories.setdefault(session_id, [])
            append_message(session_id, "bot", WELCOME_MESSAGE)
            # ensure profile object exists
            _local_profiles.setdefault(session_id, {})
            return get_chat_history_for_gradio(session_id), _local_profiles[session_id].get("name","—"), str(_local_profiles[session_id].get("age","—")), str(_local_profiles[session_id].get("height","—")), str(_local_profiles[session_id].get("weight","—")), _local_profiles[session_id].get("diagnosis","—"), ", ".join(sorted(_local_profiles[session_id].get("biomarkers", {}).keys())) if _local_profiles[session_id].get("biomarkers") else "—", session_id

        # Bind init on load
        ui.load(init, inputs=[session_state], outputs=[chatbot, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field, session_state])

        # Send message
        def on_send(session_id, text):
            if not session_id:
                session_id = new_session_id()
            return send_message(session_id, text)

        send_btn.click(on_send, inputs=[session_state, user_input], outputs=[chatbot, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field, session_state])
        user_input.submit(on_send, inputs=[session_state, user_input], outputs=[chatbot, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field, session_state])

        # Upload
        def on_upload(session_id, file_obj):
            if not session_id:
                session_id = new_session_id()
            hist, sid = upload_file(session_id, file_obj)
            # return chat history + session id into UI
            profile = fetch_profile_from_backend(sid) or _local_profiles.get(sid, {})
            return hist, sid, profile.get("name","—"), profile.get("age","—"), profile.get("height","—"), profile.get("weight","—"), profile.get("diagnosis","—"), ", ".join(sorted(profile.get("biomarkers", {}).keys())) if profile.get("biomarkers") else "—"

        upload.change(on_upload, inputs=[session_state, upload], outputs=[chatbot, session_state, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field])

        # Parse labs
        parse_btn.click(parse_labs, inputs=[session_state], outputs=[chatbot, session_state, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field])

        # Meal plan
        mealplan_btn.click(request_mealplan, inputs=[session_state], outputs=[chatbot, session_state, name_field, age_field, height_field, weight_field, diagnosis_field, biomarkers_field])

    return ui

# -------------------------
# Launch
# -------------------------
if __name__ == "__main__":
    # Ensure Flask backend is running before launching UI (user requested)
    print(f"Starting NutriNest Gradio UI (expecting Flask backend at {BACKEND_URL})")
    ui = build_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860, share=False)