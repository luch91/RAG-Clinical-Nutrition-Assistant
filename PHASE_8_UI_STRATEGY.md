# PHASE 8: UI IMPLEMENTATION STRATEGY
## Clinical Pediatric Nutrition RAG Chatbot

---

## 🎯 OBJECTIVES

1. **Clean Architecture**: Separate concerns (API, UI, Business Logic)
2. **Therapy Flow UI**: Support 7-step therapy flow with visual feedback
3. **Profile Summary Card**: Display therapy progress visually
4. **3-Option Nudge**: Interactive buttons for Upload/Step-by-step/General
5. **Meal Plan Export**: Download 3-day plans as PDF/CSV
6. **Responsive Design**: Mobile-first, accessible, clean UX

---

## 🔍 CURRENT STATE ANALYSIS

### **Existing Architecture**
```
app/
├── application.py           # Flask backend (7 routes)
├── launch_gradio.py         # Gradio UI frontend
└── components/
    └── llm_response_manager.py  # Business logic
```

### **Issues Identified**

#### **1. Flask Backend (application.py)**
❌ **Problems:**
- Monolithic `/chat` endpoint handles ALL query types
- No separation for therapy vs recommendation flows
- No Profile Summary Card endpoint
- No meal plan export endpoint
- Error handling is basic (returns 500 for all errors)
- No structured response format for therapy flow steps

✅ **Needed:**
- Dedicated `/therapy` endpoint for 7-step flow
- `/profile_card` endpoint for card rendering
- `/meal_plan/export` endpoint (PDF/CSV)
- Structured JSON responses with step metadata
- Better error codes (400 bad request, 404 not found, 500 server error)

#### **2. Gradio UI (launch_gradio.py)**
❌ **Problems:**
- Chatbot interface only (no structured UI for therapy)
- No visual progress indicator for 7 steps
- Profile Summary Card not rendered
- 3-Option Nudge is text-only (should be buttons)
- No meal plan preview/download UI
- Session management is local dict (not persistent)

✅ **Needed:**
- **Therapy Flow Panel**: Show current step (1/7) with progress bar
- **Profile Card Panel**: Display card with sections for each step
- **3-Option Nudge Panel**: Interactive buttons instead of text
- **Meal Plan Preview**: Table view with nutrient totals
- **Download Buttons**: PDF/CSV export for meal plans
- **Better Session Persistence**: Use backend session storage

---

## 🏗️ NEW UI ARCHITECTURE (Recommended)

### **Option A: Enhanced Gradio UI (Quickest - 1-2 hours)**

**Pros:**
- Leverage existing Gradio components
- Fast to implement
- Python-only (no JS needed)
- Good for MVP/demo

**Cons:**
- Limited customization
- Not ideal for complex flows
- Mobile experience suboptimal

**Implementation:**
```python
import gradio as gr

with gr.Blocks(theme="soft") as app:
    gr.Markdown("# 🪶 NutriNest - Clinical Pediatric Nutrition")

    with gr.Tabs():
        # Tab 1: Chat Interface (existing)
        with gr.Tab("💬 Chat"):
            chatbot = gr.Chatbot(height=500)
            msg_input = gr.Textbox(placeholder="Ask a nutrition question...")

        # Tab 2: Therapy Flow (NEW)
        with gr.Tab("🏥 Therapy Planning"):
            with gr.Row():
                with gr.Column(scale=2):
                    # Progress indicator
                    progress = gr.Markdown("**Step 0/7**: Not started")

                    # Profile Summary Card
                    profile_card = gr.Markdown("Profile card will appear here...")

                with gr.Column(scale=1):
                    # Actions
                    gr.Markdown("### Quick Actions")
                    start_therapy_btn = gr.Button("Start Therapy Planning")

                    # 3-Option Nudge (when data missing)
                    nudge_panel = gr.Column(visible=False)
                    with nudge_panel:
                        upload_btn = gr.Button("🅰️ Upload Medical Records")
                        stepbystep_btn = gr.Button("🅱️ Step-by-step Q&A")
                        general_btn = gr.Button("🅲️ General Info Only")

        # Tab 3: Meal Plan (NEW)
        with gr.Tab("📅 Meal Plan"):
            meal_plan_display = gr.DataFrame(label="3-Day Meal Plan")
            with gr.Row():
                export_pdf_btn = gr.Button("📄 Export as PDF")
                export_csv_btn = gr.Button("📊 Export as CSV")
```

**Structure:**
- **Tab 1 (Chat)**: Existing chatbot interface for general queries
- **Tab 2 (Therapy)**: Progress tracker + Profile Card + Nudge buttons
- **Tab 3 (Meal Plan)**: Table view + export buttons

---

### **Option B: Modern Web UI with Streamlit (Moderate - 2-3 hours)**

**Pros:**
- Better UX/UI components
- Easier state management
- More customizable than Gradio
- Still Python-only

**Cons:**
- Requires Streamlit installation
- Different deployment model
- Learning curve if unfamiliar

**Implementation Sketch:**
```python
import streamlit as st

st.set_page_config(page_title="NutriNest", layout="wide")

# Sidebar: Session info
with st.sidebar:
    st.title("🪶 NutriNest")
    session_id = st.text_input("Session ID", value=st.session_state.get('session_id'))

    st.divider()
    st.metric("Therapy Step", f"{st.session_state.get('step', 0)}/7")

# Main area
tab1, tab2, tab3 = st.tabs(["💬 Chat", "🏥 Therapy", "📅 Meal Plan"])

with tab1:
    # Chat interface
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input("Ask a question..."):
        # Handle chat

with tab2:
    # Therapy flow
    col1, col2 = st.columns([2, 1])

    with col1:
        st.progress(st.session_state.get('step', 0) / 7)

        # Profile Summary Card
        if st.session_state.get('profile_card'):
            st.markdown(st.session_state['profile_card'])

    with col2:
        # 3-Option Nudge
        if st.session_state.get('show_nudge'):
            if st.button("🅰️ Upload Medical Records"):
                # Handle upload
            if st.button("🅱️ Step-by-step Q&A"):
                # Handle step-by-step
            if st.button("🅲️ General Info Only"):
                # Downgrade

with tab3:
    # Meal plan display
    if st.session_state.get('meal_plan'):
        st.dataframe(st.session_state['meal_plan'])

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📄 PDF", data=pdf_bytes, file_name="meal_plan.pdf")
        with col2:
            st.download_button("📊 CSV", data=csv_bytes, file_name="meal_plan.csv")
```

---

### **Option C: Full Web App (React + Flask) (Complex - 4-6 hours)**

**Pros:**
- Professional-grade UX
- Full customization
- Best mobile experience
- Scalable architecture

**Cons:**
- Requires JavaScript/React
- More complex deployment
- Longer development time

**Not Recommended for MVP** - Use Option A or B first

---

## 🎨 RECOMMENDED APPROACH: **Enhanced Gradio (Option A)**

### **Why Gradio?**
1. ✅ Minimal code changes (extend existing launch_gradio.py)
2. ✅ Python-only (no JS required)
3. ✅ Fast implementation (1-2 hours)
4. ✅ Works with existing Flask backend
5. ✅ Good enough for demos and testing

---

## 📋 IMPLEMENTATION PLAN (PHASE 8)

### **Step 1: Backend API Enhancements** (30 min)

**File:** `app/application.py`

**Changes:**
```python
# NEW ENDPOINT: Get Profile Summary Card
@app.route("/profile_card", methods=["GET"])
def get_profile_card():
    session_id = request.args.get("session_id")
    card = llm.get_profile_summary_card(session_id)
    if card:
        return jsonify({"card": card.format_for_display(), "step": len(card.completed_steps)})
    return jsonify({"card": None, "step": 0})

# NEW ENDPOINT: Export Meal Plan
@app.route("/meal_plan/export", methods=["POST"])
def export_meal_plan():
    data = request.get_json()
    session_id = data.get("session_id")
    format_type = data.get("format", "pdf")  # pdf or csv

    meal_plan = llm.get_meal_plan(session_id)

    if format_type == "pdf":
        pdf_bytes = generate_meal_plan_pdf(meal_plan)
        return send_file(pdf_bytes, mimetype='application/pdf', as_attachment=True, download_name='meal_plan.pdf')
    else:
        csv_data = generate_meal_plan_csv(meal_plan)
        return Response(csv_data, mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=meal_plan.csv"})

# ENHANCED: Chat endpoint returns step metadata
@app.route("/chat", methods=["POST"])
def chat():
    # ... existing code ...

    # Add metadata to response
    response_data = {
        "message": result.get("message"),
        "intent": result.get("intent"),
        "therapy_step": result.get("therapy_step", 0),  # NEW
        "show_nudge": result.get("show_nudge", False),  # NEW
        "nudge_options": result.get("nudge_options", []),  # NEW
        "profile_card_updated": result.get("profile_card_updated", False)  # NEW
    }

    return jsonify(response_data)
```

---

### **Step 2: Gradio UI Enhancement** (60-90 min)

**File:** `app/launch_gradio.py`

**Changes:**

```python
import gradio as gr

# NEW: State management for therapy flow
therapy_state = {
    "session_id": None,
    "current_step": 0,
    "profile_card": None,
    "show_nudge": False,
    "meal_plan": None
}

# NEW: Update profile card display
def update_profile_card(session_id):
    response = _get(f"/profile_card?session_id={session_id}")
    if response.get("card"):
        return response["card"], response.get("step", 0)
    return "No profile card available", 0

# NEW: Handle nudge button clicks
def handle_upload_click():
    return gr.File(visible=True, label="Upload Medical Records")

def handle_stepbystep_click():
    # Trigger step-by-step mode
    return "Switched to step-by-step mode"

def handle_general_click():
    # Downgrade to recommendation
    return "Showing general recommendations"

# NEW: Export meal plan
def export_meal_plan_pdf(session_id):
    response = _post("/meal_plan/export", {"session_id": session_id, "format": "pdf"})
    # Return download link
    return response.get("download_url")

# MAIN UI
with gr.Blocks(theme=gr.themes.Soft(), title="NutriNest") as app:
    session_id_state = gr.State(value=str(uuid.uuid4()))

    gr.Markdown("# 🪶 NutriNest - Clinical Pediatric Nutrition Assistant")

    with gr.Tabs() as tabs:
        # TAB 1: CHAT (Existing + Enhanced)
        with gr.Tab("💬 Chat", id=0):
            chatbot = gr.Chatbot(height=500, label="Conversation")

            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="Ask a nutrition question...",
                    scale=4,
                    show_label=False
                )
                send_btn = gr.Button("Send", scale=1, variant="primary")

            # File upload (hidden by default, shown when nudge triggered)
            file_upload = gr.File(
                label="Upload Medical Records (PDF/Image)",
                visible=False,
                file_types=[".pdf", ".png", ".jpg"]
            )

            examples = gr.Examples(
                examples=[
                    "Compare boiled vs fermented maize for 6-month-old",
                    "What foods are high in iron for toddlers?",
                    "8 year old with T1D, HbA1c 8.5%, need meal plan"
                ],
                inputs=msg_input
            )

        # TAB 2: THERAPY FLOW (NEW)
        with gr.Tab("🏥 Therapy Planning", id=1):
            with gr.Row():
                # Left column: Profile Card
                with gr.Column(scale=3):
                    therapy_progress = gr.Markdown("### 📊 Therapy Progress\n**Step 0/7**: Not started")

                    profile_card_display = gr.Markdown(
                        """
                        ### 📋 Profile Summary Card

                        *Profile card will appear here after therapy planning starts*

                        To begin therapy planning, return to the Chat tab and provide:
                        - Diagnosis (e.g., Type 1 Diabetes)
                        - Age, weight, height
                        - Medications
                        - Recent lab results (biomarkers)
                        """,
                        label="Profile Card"
                    )

                    refresh_card_btn = gr.Button("🔄 Refresh Card", size="sm")

                # Right column: Actions
                with gr.Column(scale=1):
                    gr.Markdown("### ⚡ Quick Actions")

                    # 3-Option Nudge Panel
                    nudge_panel = gr.Column(visible=False)
                    with nudge_panel:
                        gr.Markdown("**How would you like to proceed?**")
                        upload_records_btn = gr.Button("🅰️ Upload Medical Records", variant="secondary")
                        stepbystep_btn = gr.Button("🅱️ Step-by-step Q&A", variant="secondary")
                        general_info_btn = gr.Button("🅲️ General Info Only", variant="secondary")

                    gr.Markdown("---")

                    # Status indicators
                    status_indicators = gr.Markdown(
                        """
                        **Requirements Status:**
                        - ⬜ Diagnosis
                        - ⬜ Medications
                        - ⬜ Biomarkers
                        - ⬜ Anthropometry
                        """
                    )

        # TAB 3: MEAL PLAN (NEW)
        with gr.Tab("📅 3-Day Meal Plan", id=2):
            gr.Markdown("### 📋 Personalized Therapeutic Meal Plan")

            meal_plan_status = gr.Markdown("*Meal plan will be generated after completing therapy planning*")

            # Meal plan display (table)
            meal_plan_table = gr.DataFrame(
                label="Meal Plan",
                headers=["Day", "Meal", "Foods", "Protein (g)", "CHO (g)", "Fat (g)", "Fiber (g)"],
                visible=False
            )

            # Nutrient totals
            nutrient_summary = gr.Markdown(visible=False)

            # Export buttons
            with gr.Row(visible=False) as export_panel:
                export_pdf_btn = gr.Button("📄 Download PDF", variant="primary")
                export_csv_btn = gr.Button("📊 Download CSV", variant="secondary")

    # EVENT HANDLERS

    # Chat send
    def chat_handler(message, history, session_id):
        # Call backend /chat
        response = _post("/chat", {"session_id": session_id, "query": message})

        # Update history
        history.append((message, response.get("message", "Error")))

        # Check if nudge should be shown
        show_nudge = response.get("show_nudge", False)

        # Update profile card if therapy step progressed
        card_text = ""
        step_text = "Step 0/7"
        if response.get("profile_card_updated"):
            card_response = _get(f"/profile_card?session_id={session_id}")
            card_text = card_response.get("card", "")
            step = card_response.get("step", 0)
            step_text = f"### 📊 Therapy Progress\n**Step {step}/7**"

        return (
            history,
            "",  # Clear input
            gr.update(visible=show_nudge),  # Show/hide nudge panel
            card_text,  # Update card
            step_text  # Update progress
        )

    send_btn.click(
        chat_handler,
        inputs=[msg_input, chatbot, session_id_state],
        outputs=[chatbot, msg_input, nudge_panel, profile_card_display, therapy_progress]
    )

    # Refresh card button
    def refresh_card_handler(session_id):
        card_response = _get(f"/profile_card?session_id={session_id}")
        card_text = card_response.get("card", "No card available")
        step = card_response.get("step", 0)
        step_text = f"### 📊 Therapy Progress\n**Step {step}/7**"
        return card_text, step_text

    refresh_card_btn.click(
        refresh_card_handler,
        inputs=[session_id_state],
        outputs=[profile_card_display, therapy_progress]
    )

    # Nudge button handlers
    upload_records_btn.click(
        lambda: gr.update(visible=True),
        outputs=[file_upload]
    )

    stepbystep_btn.click(
        lambda msg, hist, sid: chat_handler("step by step", hist, sid),
        inputs=[msg_input, chatbot, session_id_state],
        outputs=[chatbot, msg_input, nudge_panel, profile_card_display, therapy_progress]
    )

    general_info_btn.click(
        lambda msg, hist, sid: chat_handler("general info", hist, sid),
        inputs=[msg_input, chatbot, session_id_state],
        outputs=[chatbot, msg_input, nudge_panel, profile_card_display, therapy_progress]
    )

app.launch(server_name="0.0.0.0", server_port=7860, share=False)
```

---

## 🎯 FINAL UI FEATURES

### **Chat Tab**
- ✅ Existing chatbot interface
- ✅ File upload (shown when nudge triggered)
- ✅ Example prompts
- ✅ Conversation history

### **Therapy Tab**
- ✅ Progress indicator (Step X/7)
- ✅ Profile Summary Card (live updates)
- ✅ 3-Option Nudge panel (interactive buttons)
- ✅ Requirements status checklist
- ✅ Refresh button

### **Meal Plan Tab**
- ✅ Table view (Day, Meal, Foods, Nutrients)
- ✅ Nutrient totals summary
- ✅ PDF export button
- ✅ CSV export button

---

## 📊 IMPLEMENTATION ESTIMATES

| Component | Time | Priority |
|-----------|------|----------|
| Backend API endpoints | 30 min | HIGH |
| Gradio UI tabs | 30 min | HIGH |
| Profile Card display | 20 min | HIGH |
| 3-Option Nudge buttons | 15 min | HIGH |
| Meal Plan table | 20 min | MEDIUM |
| PDF export | 30 min | MEDIUM |
| CSV export | 15 min | LOW |
| Polish & testing | 30 min | HIGH |
| **TOTAL** | **3 hours** | |

---

## ✅ SUCCESS CRITERIA

1. **User can see therapy progress** - Step X/7 indicator updates in real-time
2. **Profile card displays correctly** - All 7 steps populate card sections
3. **Nudge works as buttons** - Upload/Step-by-step/General are clickable
4. **Meal plan is downloadable** - PDF and CSV exports work
5. **Mobile responsive** - UI works on tablets/phones
6. **Session persistence** - Card and meal plan persist across page reloads

---

## 🚀 DEPLOYMENT NOTES

**To run the new UI:**

```bash
# Terminal 1: Start Flask backend
python -m app.application

# Terminal 2: Start Gradio UI
python -m app.launch_gradio
```

**Access:**
- Gradio UI: `http://localhost:7860`
- Flask API: `http://localhost:5000`

---

**This strategy provides a clean, professional UI that supports the full 7-step therapy flow with minimal code changes.**
