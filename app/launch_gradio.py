"""
Gradio UI for Clinical Pediatric Nutrition RAG Chatbot

Features:
- Conversational chat interface
- Lab upload with OCR
- Dynamic quick action buttons
- Citation display
- Therapy output visualization
"""

import gradio as gr
import os
import json
from typing import Dict, Any, List, Tuple, Optional
from app.components.llm_response_manager import LLMResponseManager
from app.components.vector_store import load_vector_store
from app.components.hybrid_retriever import init_retriever
from app.common.logger import get_logger

logger = get_logger(__name__)

# Initialize vector store
try:
    vector_store = load_vector_store()
    if vector_store:
        init_retriever(vector_store)
        logger.info("Vector store loaded successfully")
    else:
        logger.warning("Vector store not found - running without RAG")
except Exception as e:
    logger.error(f"Failed to load vector store: {str(e)}")

# Initialize LLM Response Manager (replaces ChatOrchestrator)
orchestrator = LLMResponseManager()

# Custom CSS for professional look
custom_css = """
.gradio-container {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    max-width: 1400px;
}

.chat-message {
    border-radius: 12px;
    padding: 16px;
}

#lab-upload-btn.highlight {
    animation: pulse 2s infinite;
    border: 3px solid #10b981 !important;
    background: #d1fae5 !important;
}

@keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    50% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
}

.citation-box {
    background: #f8fafc;
    border-left: 4px solid #3b82f6;
    padding: 12px;
    margin: 8px 0;
    border-radius: 4px;
}

.quick-action-btn {
    margin: 4px;
    font-size: 14px;
}

.profile-card {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 8px;
    padding: 12px;
}

.therapy-output-card {
    background: #eff6ff;
    border: 2px solid #3b82f6;
    border-radius: 8px;
    padding: 16px;
    margin-top: 12px;
}
"""

# Welcome message
def get_welcome_message():
    """Generate custom welcome message"""
    return [[None, """👋 **Welcome to the Clinical Pediatric Nutrition Assistant!**

I provide evidence-based nutrition guidance for pediatric patients (0-18 years).

**I can help with:**

🔹 **Food Comparisons**
   _Example: "Compare boiled maize vs fermented maize for a 6-month-old"_

🔹 **General Nutrition Questions**
   _Example: "What foods are high in iron for toddlers?"_

🔹 **Dietary Recommendations** (diagnosis-based)
   _Example: "My 8-year-old has type 1 diabetes, what should they eat?"_

🔹 **Clinical Therapy Plans** (biomarker-driven nutrition therapy)
   _Supported conditions:_
   • Preterm Nutrition
   • Type 1 Diabetes
   • Food Allergy
   • Cystic Fibrosis
   • Inherited Metabolic Disorders (PKU, MSUD, Galactosemia)
   • Epilepsy / Ketogenic Therapy
   • Chronic Kidney Disease
   • GI Disorders (IBD / GERD)

   _Example: "10yo with type 1 diabetes, HbA1c 8.5%, glucose 150 mg/dL. Need meal plan."_

**Getting Started:**
• For therapy plans: Provide diagnosis, age, weight, height, and biomarkers
• For food comparisons: Specify age and preparation method
• All recommendations are evidence-based with clinical citations

**What would you like to know today?**

---
_⚠️ For educational purposes only. Not medical advice. Consult a healthcare provider._
"""]]


# Citation formatting
def format_citations(sources: List[Any], citations: List[Dict[str, Any]]) -> str:
    """Format citations in academic style"""
    if not sources and not citations:
        return "*No citations yet. Start a conversation to see references.*"

    formatted = ["### 📚 Clinical Sources\n"]

    # Group citations by type
    clinical_texts = [c for c in citations if c.get('type') == 'guideline']
    fct_refs = [c for c in citations if c.get('type') == 'fct']

    if clinical_texts:
        formatted.append("**Clinical Textbooks & Guidelines:**")
        for idx, source in enumerate(clinical_texts, 1):
            title = source.get('title', 'Unknown')
            year = source.get('year', '')
            citation = f"**[{idx}]** {title}"
            if year:
                citation += f" ({year})"
            formatted.append(citation)
        formatted.append("")

    if fct_refs:
        formatted.append("**Food Composition Tables:**")
        for idx, source in enumerate(fct_refs, len(clinical_texts) + 1):
            food = source.get('food', 'Unknown food')
            country = source.get('country_label', '')
            ref = source.get('ref', '')
            citation = f"**[{idx}]** {food}"
            if country:
                citation += f" ({country} FCT)"
            if ref:
                citation += f", Ref: {ref}"
            formatted.append(citation)

    return "\n".join(formatted)


# Lab upload processing (placeholder - will implement OCR)
def process_lab_upload(file_path: Optional[str]) -> Dict[str, Any]:
    """Process uploaded lab results (PDF/Image)"""
    if not file_path:
        return {"success": False, "error": "No file uploaded"}

    try:
        file_ext = os.path.splitext(file_path)[1].lower()

        if file_ext == '.pdf':
            # TODO: Implement PDF text extraction with pdfplumber
            return {
                "success": False,
                "error": "PDF processing not yet implemented. Please enter values manually."
            }

        elif file_ext in ['.jpg', '.jpeg', '.png']:
            # TODO: Implement OCR with pytesseract
            return {
                "success": False,
                "error": "Image OCR not yet implemented. Please enter values manually."
            }

        else:
            return {"success": False, "error": "Unsupported file type"}

    except Exception as e:
        logger.error(f"Lab upload processing failed: {str(e)}")
        return {"success": False, "error": str(e)}


# Main chat response handler
def respond(
    message: str,
    chat_history: List[List[str]],
    profile_state: Dict[str, Any]
) -> Tuple:
    """
    Handle user message and return updated chat, citations, profile, and UI states
    """
    if not message or not message.strip():
        return chat_history, "", "", profile_state, False, gr.update(visible=False), "", "", ""

    try:
        # Call orchestrator
        response = orchestrator.handle_query(message.strip())

        # Extract components
        answer = response.get('answer', 'No response generated')
        sources = response.get('sources_used', [])
        citations = response.get('citations', [])
        classification = response.get('classification', {})
        quick_actions = response.get('quick_actions', [])
        highlight_upload = response.get('highlight_upload_button', False)

        # Update chat history
        chat_history.append([message, answer])

        # Format citations
        citations_md = format_citations(sources, citations)

        # Update profile display
        if classification:
            profile_state.update({
                "diagnosis": classification.get("diagnosis"),
                "medications": classification.get("medications", []),
                "biomarkers": classification.get("biomarkers", []),
                "label": classification.get("label")
            })

        profile_json = json.dumps(profile_state, indent=2)

        # Configure quick action buttons
        qa_visible = len(quick_actions) > 0
        qa1 = quick_actions[0] if len(quick_actions) > 0 else ""
        qa2 = quick_actions[1] if len(quick_actions) > 1 else ""
        qa3 = quick_actions[2] if len(quick_actions) > 2 else ""

        return (
            chat_history,
            citations_md,
            profile_json,
            profile_state,
            highlight_upload,
            gr.update(visible=qa_visible),
            qa1,
            qa2,
            qa3
        )

    except Exception as e:
        logger.error(f"Chat response error: {str(e)}")
        error_msg = f"⚠️ Error: {str(e)}\n\nPlease try again or rephrase your question."
        chat_history.append([message, error_msg])
        return chat_history, "", "", profile_state, False, gr.update(visible=False), "", "", ""


# Quick action button click handler
def handle_quick_action(button_text: str, chat_history: List[List[str]], profile_state: Dict[str, Any]) -> Tuple:
    """Handle quick action button clicks"""
    return respond(button_text, chat_history, profile_state)


# Lab upload handler
def handle_lab_upload(file_path: Optional[str], chat_history: List[List[str]], profile_state: Dict[str, Any]) -> Tuple:
    """Handle lab result file upload"""
    if not file_path:
        return chat_history, "", profile_state, False, gr.update(visible=False), "", "", ""

    result = process_lab_upload(file_path)

    if result.get("success"):
        biomarkers = result.get("biomarkers", {})

        # Format biomarker list
        biomarker_lines = []
        for name, data in biomarkers.items():
            biomarker_lines.append(f"• **{name.title()}**: {data['value']} {data['unit']}")

        bot_msg = f"""📋 **Lab Results Processed!**

**Extracted Biomarkers:**
{chr(10).join(biomarker_lines)}

✅ Values have been added to patient profile.

What medications is the patient currently taking?

_List them separated by commas (e.g., "enalapril, furosemide")_
_Or type "none" if not on any medications_
"""

        chat_history.append([f"📎 Uploaded: {os.path.basename(file_path)}", bot_msg])
        profile_state["biomarkers_detailed"] = biomarkers

    else:
        # Extraction failed
        error_msg = f"""⚠️ **Could not extract biomarkers from file**

{result.get('error', 'Unknown error')}

**Please try:**
• Ensuring image is clear and well-lit
• Using a different file format
• Manually entering values (type "step by step")

Would you like to try manual entry instead?
"""
        chat_history.append([f"📎 Uploaded: {os.path.basename(file_path)}", error_msg])

    return chat_history, "", profile_state, False, gr.update(visible=False), "", "", ""


# Reset session handler
def reset_session() -> Tuple:
    """Reset the chat session"""
    orchestrator.reset_session()
    return (
        get_welcome_message(),  # chat_history
        "*No citations yet.*",  # citations
        "{}",  # profile_json
        {},  # profile_state
        False,  # upload_highlight
        gr.update(visible=False),  # quick_actions_row
        "",  # qa1
        "",  # qa2
        ""  # qa3
    )


# Build Gradio interface
with gr.Blocks(theme=gr.themes.Soft(), css=custom_css, title="Clinical Pediatric Nutrition Assistant") as app:
    # Header
    gr.Markdown("# 🏥 Clinical Pediatric Nutrition Assistant")
    gr.Markdown("_Evidence-based nutrition guidance for pediatric conditions (0-18 years)_")

    # State management
    profile_state = gr.State({})

    with gr.Row():
        # ============================================
        # LEFT PANEL: Chat Interface (60% width)
        # ============================================
        with gr.Column(scale=6):
            # Chat history
            chatbot = gr.Chatbot(
                value=get_welcome_message(),
                height=600,
                label="Conversation",
                show_label=False,
                avatar_images=(None, "🤖")
            )

            # Input area
            with gr.Row():
                msg = gr.Textbox(
                    label="Your message",
                    placeholder="Describe your nutrition question or patient case...",
                    lines=2,
                    scale=5,
                    show_label=False
                )

                send_btn = gr.Button("Send", variant="primary", scale=1)

            # File upload for lab results
            with gr.Row():
                lab_upload = gr.File(
                    label="📋 Upload Lab Results (PDF/Photo)",
                    file_types=[".pdf", ".jpg", ".jpeg", ".png"],
                    type="filepath",
                    elem_id="lab-upload-btn"
                )

            # Quick action buttons (shown dynamically)
            with gr.Row(visible=False) as quick_actions_row:
                gr.Markdown("**Quick Response:**")
                qa_btn_1 = gr.Button("", size="sm", elem_classes=["quick-action-btn"])
                qa_btn_2 = gr.Button("", size="sm", elem_classes=["quick-action-btn"])
                qa_btn_3 = gr.Button("", size="sm", elem_classes=["quick-action-btn"])

            # Hidden state for upload highlight
            upload_highlight = gr.State(False)

        # ============================================
        # RIGHT PANEL: Context & Citations (40% width)
        # ============================================
        with gr.Column(scale=4):
            # Session profile card
            with gr.Accordion("👤 Patient Profile", open=True):
                profile_json = gr.Code(
                    value="{}",
                    language="json",
                    label="Extracted Information"
                )
                with gr.Row():
                    reset_btn = gr.Button("🔄 Reset Session", size="sm", variant="secondary")

            # Citations Section (Always Visible)
            with gr.Accordion("📚 Clinical Sources & Citations", open=True):
                gr.Markdown("_Evidence-based references used in this response_")

                citations_display = gr.Markdown(
                    value="*No citations yet. Start a conversation to see references.*",
                    label="Citations"
                )

            # System info
            with gr.Accordion("ℹ️ System Info", open=False):
                gr.Markdown("""
**Model Routing:**
• Therapy queries → DeepSeek-R1-Distill-Llama-70B
• General/Comparison/Recommendation → Llama-3.2-3B

**Features:**
• 4-intent classification (comparison, general, recommendation, therapy)
• Therapy gatekeeper (requires medications + biomarkers)
• Context-aware follow-ups (one question at a time)
• Rejection handling with graceful degradation
                """)

    # ============================================
    # Event Handlers
    # ============================================

    # Send button click
    send_btn.click(
        fn=respond,
        inputs=[msg, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    ).then(
        lambda: "",  # Clear input
        outputs=[msg]
    )

    # Enter key in textbox
    msg.submit(
        fn=respond,
        inputs=[msg, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    ).then(
        lambda: "",  # Clear input
        outputs=[msg]
    )

    # Quick action button clicks
    qa_btn_1.click(
        fn=handle_quick_action,
        inputs=[qa_btn_1, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    )

    qa_btn_2.click(
        fn=handle_quick_action,
        inputs=[qa_btn_2, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    )

    qa_btn_3.click(
        fn=handle_quick_action,
        inputs=[qa_btn_3, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    )

    # Lab upload
    lab_upload.change(
        fn=handle_lab_upload,
        inputs=[lab_upload, chatbot, profile_state],
        outputs=[chatbot, citations_display, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    )

    # Reset session
    reset_btn.click(
        fn=reset_session,
        outputs=[chatbot, citations_display, profile_json, profile_state, upload_highlight, quick_actions_row, qa_btn_1, qa_btn_2, qa_btn_3]
    )


if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )
