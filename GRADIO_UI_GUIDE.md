# Gradio UI Guide - Clinical Pediatric Nutrition Assistant

## Quick Start

### Installation

```bash
# Install Gradio and OCR dependencies
pip install gradio==4.44.0 pdfplumber pytesseract Pillow

# Note: pytesseract requires Tesseract-OCR to be installed on your system
# Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
# Linux: sudo apt install tesseract-ocr
# Mac: brew install tesseract
```

### Launch

```bash
python launch_gradio.py
```

Then open your browser to: `http://localhost:7860`

---

## UI Overview

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Clinical Pediatric Nutrition Assistant                                  │
├──────────────────────────┬──────────────────────────────────────────────┤
│ CHAT INTERFACE (Left)    │ CONTEXT PANEL (Right)                        │
│                          │                                              │
│ • Conversational chat    │ • Patient Profile (extracted data)           │
│ • Message input          │ • Clinical Sources & Citations              │
│ • Lab upload button      │ • System Info                                │
│ • Quick action buttons   │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

---

## Features

### 1. **Custom Welcome Message**

**What it does:**
- Educates users about 4 intent types
- Provides concrete examples
- Sets expectations for therapy requirements

**Example:**
```
👋 Welcome to the Clinical Pediatric Nutrition Assistant!

I can help with:
🔹 Food Comparisons
   Example: "Compare boiled maize vs fermented maize for a 6-month-old"

🔹 General Nutrition Questions
   Example: "What foods are high in iron for toddlers?"

🔹 Dietary Recommendations
   Example: "My 8-year-old has type 1 diabetes, what should they eat?"

🔹 Clinical Therapy Plans (requires medications + lab results)
   Example: "10yo with epilepsy, on phenytoin, HbA1c 8.5%. Need meal plan."
```

---

### 2. **Therapy Onboarding Flow**

**Triggered when:**
- User explicitly requests therapy ("I need diet therapy for ckd")
- Missing 2+ critical slots (medications, biomarkers, age, weight)

**User Journey:**

```
User: "I need diet therapy for ckd"
  ↓
Bot: 🎯 CKD Diet Therapy - Let's Get Started!

Required Information:
❌ Patient age
❌ Current medications
❌ Recent lab results (creatinine, eGFR, potassium, phosphate)
❌ Weight & height

How would you like to proceed?

📋 Option 1: Upload Lab Results (Fastest)
✍️ Option 2: Answer Step-by-Step (4 questions)
📚 Option 3: General CKD Information First

[Upload Lab Results] [Step by Step] [General Info First]
  ↓
User clicks: [Step by Step]
  ↓
Bot: ✍️ Step-by-Step Data Collection (Question 1/7)

What is the patient's age?
[5] [8] [10] [12] [15]
```

---

### 3. **Dynamic Quick Action Buttons**

**When shown:**
- Bot asks multiple-choice question
- Rejection handling (Yes/No/Skip)
- Data collection method choice

**Examples:**

**Age Selection:**
```
Bot: "What is the patient's age?"
[5] [8] [10] [12] [15]
```

**Rejection Options:**
```
Bot: "Lab results not available. Would you like:"
[General Recommendations] [Upload Labs] [Come Back Later]
```

**Data Entry Method:**
```
Bot: "How would you like to proceed?"
[Upload Lab Results] [Step by Step] [General Info First]
```

---

### 4. **Lab Upload with OCR**

**Supported Formats:**
- PDF (`.pdf`)
- Images (`.jpg`, `.jpeg`, `.png`)

**Processing Flow:**

```
1. User clicks "📋 Upload Lab Results"
2. Selects PDF or photo
3. System extracts biomarkers:
   • Creatinine: 2.1 mg/dL
   • eGFR: 45 mL/min/1.73m²
   • Potassium: 5.2 mEq/L
4. Bot shows preview: "Extracted biomarkers: ..."
5. User confirms or edits
6. Values added to profile
7. Bot continues: "Great! Now medications..."
```

**Current Status:**
- PDF extraction: Placeholder (implement with `pdfplumber`)
- Image OCR: Placeholder (implement with `pytesseract`)
- Fallback: Manual entry with "step by step" option

---

### 5. **Citation Display**

**Always Visible:** Right panel shows clinical sources

**Format:**

```
📚 Clinical Sources & Citations

Clinical Textbooks & Guidelines:
[1] Shaw, V., et al. (2020). Clinical Paediatric Dietetics (5th ed.)
[2] Dietary Reference Intakes (2006). The Essential Guide

Food Composition Tables:
[3] Maize, boiled (Nigerian FCT), Ref: cereals:045
[4] Rice, white (USDA 2023), Ref: grains:20450
```

**Citation Types:**
- `guideline`: Clinical textbooks, DRI, guidelines
- `fct`: Food composition table entries

---

### 6. **Patient Profile Card**

**Displays:**
```json
{
  "diagnosis": "CKD",
  "medications": ["enalapril", "furosemide"],
  "biomarkers": ["creatinine", "egfr", "potassium"],
  "label": "therapy",
  "age": 10,
  "weight_kg": 35
}
```

**Features:**
- Real-time updates as data extracted
- JSON format for transparency
- Reset button to clear session

---

## Usage Examples

### Example 1: Therapy Query with All Data

```
User: "10yo with epilepsy, on phenytoin, HbA1c 8.5%. Need meal plan."
  ↓
Bot extracts:
  • Diagnosis: Epilepsy
  • Age: 10
  • Medications: phenytoin
  • Biomarkers: HbA1c 8.5%
  ↓
Bot: ✅ Therapy gatekeeper passed!
  ↓
Bot: [Generates therapy output with citations]

Profile Card Updates:
{
  "diagnosis": "Epilepsy",
  "medications": ["phenytoin"],
  "biomarkers": ["hba1c"],
  "label": "therapy",
  "age": 10
}

Citations:
[1] Clinical Paediatric Dietetics (2020), Chapter 8: Epilepsy
[2] Drug-Nutrient Interactions, Phenytoin section
```

---

### Example 2: Therapy Query WITHOUT Data

```
User: "I need diet therapy for ckd"
  ↓
Bot: 🎯 CKD Diet Therapy - Let's Get Started!

Missing:
❌ Age, medications, lab results, weight

Options:
[Upload Lab Results] [Step by Step] [General Info First]
  ↓
User: "step by step"
  ↓
Bot: Q1: What is the patient's age?
[5] [8] [10] [12] [15]
  ↓
User: [10]
  ↓
Bot: ✅ Age: 10 years
     Q2: What is the patient's weight?
  ↓
User: "35kg"
  ↓
Bot: ✅ Weight: 35 kg
     Q3: Current medications?
  ↓
... continues for 7 questions ...
  ↓
Bot: [Therapy output]
```

---

### Example 3: Rejection Handling

```
User: "10yo diabetes, need plan"
  ↓
Bot: Medications?
  ↓
User: "no"
  ↓
Bot: I understand you're not on medications.

Would you like:
1. General nutritional recommendations (no meds needed)
2. Wait - I'll get my medication list

[General Recommendations] [Come Back Later]
  ↓
User: [General Recommendations]
  ↓
Bot: [Provides general T1D diet guidelines with citations]
```

---

### Example 4: Comparison Query

```
User: "Compare for 6 month old"
  ↓
Bot: What food to compare?
[Maize] [Rice] [Cassava] [Plantain]
  ↓
User: [Maize]
  ↓
Bot: What preparations?
[Raw vs Boiled] [Boiled vs Fermented] [All Available]
  ↓
User: [Boiled vs Fermented]
  ↓
Bot: Comparing boiled maize vs fermented maize for 6-month-old:

Boiled Maize:
• Protein: 3.2g per 100g
• Iron: 0.5mg per 100g

Fermented Maize:
• Protein: 2.8g per 100g
• Iron: 0.8mg per 100g (better absorption)

Recommendation: Fermented maize preferred...

Citations:
[1] Nigerian FCT (2023), Cereals section
[2] Shaw et al. (2020), Chapter 5: Infant Feeding
```

---

## Model Routing

**Automatic routing based on intent:**

| Intent | Model | Why |
|--------|-------|-----|
| **Therapy** | DeepSeek-R1-Distill-Llama-70B | Clinical reasoning, therapy calculations |
| **General** | Llama-3.2-3B | Fast, cost-effective |
| **Comparison** | Llama-3.2-3B | Fast, cost-effective |
| **Recommendation** | Llama-3.2-3B | Fast, cost-effective |

**Cost savings:** ~70% reduction by using Llama for non-therapy queries

---

## Technical Details

### Architecture

```
User Input
  ↓
Gradio UI (gradio_app.py)
  ↓
Chat Orchestrator (chat_orchestrator.py)
  ↓
Query Classifier (distilbert-classifier-v2)
  ↓
Therapy Gatekeeper (medications + biomarkers check)
  ↓
├─ PASS → Therapy Flow
│    ↓
│    DeepSeek-R1 + Hybrid Retriever + Citations
│
└─ FAIL → Onboarding Flow
     ↓
     Options: Upload / Step-by-Step / General Info
```

### State Management

**Gradio State Variables:**
- `profile_state`: Dict of extracted patient data
- `upload_highlight`: Bool to trigger upload button animation
- `quick_actions_row`: Visibility of quick action buttons

**Orchestrator Session State:**
- `session_slots`: Persistent profile across turns
- `_awaiting_slot`: Current slot being collected
- `_intent_lock`: Locked intent for follow-up sequence

---

## Deployment

### Local Development

```bash
python launch_gradio.py
```

### Production (HuggingFace Spaces)

1. Create `app.py` in repo root:
```python
from app.gradio_app import app
app.launch()
```

2. Add `requirements.txt`

3. Push to HuggingFace Space

4. Space URL: `https://huggingface.co/spaces/YOUR_USERNAME/nutrition-assistant`

---

## Troubleshooting

### Issue: "No module named 'app'"

**Solution:**
```bash
# Ensure you're in project root
cd "C:\Users\user\Desktop\MLOPS AI Projects\NUTRITION RAG CHATBOT"
python launch_gradio.py
```

### Issue: Tesseract not found for OCR

**Solution:**
```bash
# Windows
# Download from https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH: C:\Program Files\Tesseract-OCR

# Linux
sudo apt install tesseract-ocr

# Mac
brew install tesseract
```

### Issue: Vector store not found

**Solution:**
```bash
# Create vector store first
python -c "from app.components.pdf_loader import load_and_save_chunks; load_and_save_chunks()"
```

### Issue: Quick action buttons not showing

**Check:**
1. Response includes `quick_actions` field
2. `quick_actions_row` visibility set to `True`
3. Button text not empty

---

## Future Enhancements

### Phase 1 (Complete)
- ✅ Therapy onboarding flow
- ✅ Dynamic quick actions
- ✅ Citation display
- ✅ Custom welcome message

### Phase 2 (Planned)
- [ ] Implement PDF OCR (pdfplumber)
- [ ] Implement Image OCR (pytesseract)
- [ ] Biomarker value validation
- [ ] Therapy output visualization (charts)

### Phase 3 (Planned)
- [ ] Session export (PDF report)
- [ ] Session save/load (JSON)
- [ ] Voice input
- [ ] Multi-language support

---

## Support

**Issues:** https://github.com/YOUR_USERNAME/nutrition-chatbot/issues

**Docs:** See `IMPLEMENTATION_SUMMARY.md` for technical details

**Contact:** [Your Email]

---

**Version:** 1.0.0
**Last Updated:** 2025-10-14
