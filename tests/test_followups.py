import pytest
from app.components.followup_question_generator import generate_follow_up_questions

# --- Test Data ---
test_cases = [
    (
        "Compare the protein content in bambara nuts and cowpeas",
        {"label": "comparison", "needs_followup": True, "biomarkers": []}
    ),
    (
        "I want to lose weight, what diet should I follow?",
        {"label": "recommendation", "needs_followup": True, "biomarkers": []}
    ),
    (
        "What foods should I avoid if I have kidney disease?",
        {"label": "therapy", "needs_followup": True, "biomarkers": []}
    ),
    (
        "What is vitamin C?",
        {"label": "general", "needs_followup": False, "biomarkers": ["vitamin_c"]}
    ),
]

@pytest.mark.parametrize("query, expected", test_cases)
def test_generate_follow_up_questions(query, expected):
    classification, followups = generate_follow_up_questions(query)

    # --- Classification checks ---
    assert isinstance(classification, dict)

    assert classification["label"] == expected["label"]
    assert classification["needs_followup"] == expected["needs_followup"]
    assert classification["biomarkers"] == expected["biomarkers"]

    # --- Follow-up checks ---
    if expected["needs_followup"]:
        assert len(followups) > 0
    else:
        assert len(followups) == 0
