"""
Test Phase 7: Final Integration Test (No Unicode)

Tests that all Phase 7 components are properly imported and initialized.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_imports():
    """Test that all Phase 7 components can be imported."""
    print("\n" + "="*80)
    print("TEST 1: Component Imports")
    print("="*80)

    try:
        from app.components.therapy_generator import TherapyGenerator
        print("[OK] TherapyGenerator imported")

        from app.components.fct_manager import FCTManager
        print("[OK] FCTManager imported")

        from app.components.meal_plan_generator import MealPlanGenerator
        print("[OK] MealPlanGenerator imported")

        from app.components.citation_manager import CitationManager
        print("[OK] CitationManager imported")

        from app.components.profile_summary_card import ProfileSummaryCard
        print("[OK] ProfileSummaryCard imported")

        from app.components.llm_response_manager import LLMResponseManager
        print("[OK] LLMResponseManager imported")

        return True
    except Exception as e:
        print(f"[FAIL] Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_manager_initialization():
    """Test that LLMResponseManager initializes with therapy components."""
    print("\n" + "="*80)
    print("TEST 2: LLMResponseManager Initialization")
    print("="*80)

    try:
        from app.components.llm_response_manager import LLMResponseManager

        print("\nInitializing manager...")
        manager = LLMResponseManager(dri_table_path="data/dri_table.csv")

        # Check that therapy components exist
        print("\nChecking therapy components:")

        if hasattr(manager, 'therapy_gen'):
            print(f"[OK] therapy_gen: {type(manager.therapy_gen).__name__}")
        else:
            print("[FAIL] therapy_gen not found")
            return False

        if hasattr(manager, 'fct_mgr'):
            print(f"[OK] fct_mgr: {type(manager.fct_mgr).__name__}")
        else:
            print("[FAIL] fct_mgr not found")
            return False

        if hasattr(manager, 'meal_plan_gen'):
            print(f"[OK] meal_plan_gen: {type(manager.meal_plan_gen).__name__}")
        else:
            print("[FAIL] meal_plan_gen not found")
            return False

        # Check that original components still exist
        print("\nChecking original components:")
        if hasattr(manager, 'classifier'):
            print(f"[OK] classifier: {type(manager.classifier).__name__}")
        else:
            print("[FAIL] classifier not found")
            return False

        if hasattr(manager, 'followup_gen'):
            print(f"[OK] followup_gen: {type(manager.followup_gen).__name__}")
        else:
            print("[FAIL] followup_gen not found")
            return False

        if hasattr(manager, 'computation'):
            print(f"[OK] computation: {type(manager.computation).__name__}")
        else:
            print("[FAIL] computation not found")
            return False

        print("\n[OK] All components initialized successfully")
        return True

    except Exception as e:
        print(f"[FAIL] Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_profile_card_initialization():
    """Test ProfileSummaryCard initialization."""
    print("\n" + "="*80)
    print("TEST 3: ProfileSummaryCard Initialization")
    print("="*80)

    try:
        from app.components.profile_summary_card import ProfileSummaryCard

        patient_info = {
            "age": 8,
            "sex": "M",
            "weight_kg": 25.0,
            "height_cm": 125.0,
            "diagnosis": "Type 1 Diabetes",
            "medications": ["Insulin 20 units"],
            "biomarkers": {"HbA1c": {"value": 8.5, "unit": "%"}},
            "country": "Kenya",
            "allergies": []
        }

        print("\nInitializing profile card...")
        card = ProfileSummaryCard.initialize_card(patient_info)

        print("[OK] Profile card initialized")
        print(f"  Patient: {card.patient_info.get('age')}yo {card.patient_info.get('sex')}")
        print(f"  Diagnosis: {card.patient_info.get('diagnosis')}")

        # Test display
        print("\nGenerating card display...")
        display = card.format_for_display()

        if display and len(display) > 0:
            print("[OK] Card display generated")
            print(f"  Length: {len(display)} characters")
            # Print first 3 lines
            lines = display.split('\n')
            for line in lines[:3]:
                print(f"  {line}")
        else:
            print("[FAIL] Card display empty")
            return False

        return True

    except Exception as e:
        print(f"[FAIL] ProfileSummaryCard test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_citation_manager():
    """Test CitationManager."""
    print("\n" + "="*80)
    print("TEST 4: CitationManager")
    print("="*80)

    try:
        from app.components.citation_manager import CitationManager

        print("\nInitializing citation manager...")
        citations = CitationManager()

        # Add some citations
        citations.add_citation(
            source="WHO/FAO DRI",
            context="Baseline requirements",
            source_type="dri"
        )

        citations.add_citation(
            source="Clinical Paediatric Dietetics",
            chapter="Chapter 12",
            page="456",
            context="T1D adjustments",
            source_type="clinical"
        )

        print("[OK] Citations added")

        # Get formatted citations
        formatted = citations.get_grouped_citations()

        if formatted and len(formatted) > 0:
            print("[OK] Citations formatted")
            print(f"  Length: {len(formatted)} characters")
            # Print first 5 lines (non-unicode safe)
            lines = formatted.split('\n')
            for i, line in enumerate(lines[:5]):
                try:
                    print(f"  {line}")
                except:
                    print(f"  [Line {i+1} contains special characters]")
        else:
            print("[FAIL] Citations empty")
            return False

        return True

    except Exception as e:
        print(f"[FAIL] CitationManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_handle_therapy_exists():
    """Test that _handle_therapy method exists and has correct signature."""
    print("\n" + "="*80)
    print("TEST 5: _handle_therapy Method Check")
    print("="*80)

    try:
        from app.components.llm_response_manager import LLMResponseManager

        manager = LLMResponseManager(dri_table_path="data/dri_table.csv")

        # Check method exists
        if not hasattr(manager, '_handle_therapy'):
            print("[FAIL] _handle_therapy method not found")
            return False

        print("[OK] _handle_therapy method exists")

        # Check method signature
        import inspect
        sig = inspect.signature(manager._handle_therapy)
        params = list(sig.parameters.keys())

        print(f"  Parameters: {', '.join(params)}")

        expected_params = ['session_id', 'query', 'session', 'query_info']
        if params == expected_params:
            print("[OK] Method signature correct")
        else:
            print(f"[FAIL] Expected params: {expected_params}")
            print(f"  Got params: {params}")
            return False

        return True

    except Exception as e:
        print(f"[FAIL] Method check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("PHASE 7: INTEGRATION TESTS")
    print("=" * 80)

    # Run tests
    test1 = test_imports()
    test2 = test_manager_initialization()
    test3 = test_profile_card_initialization()
    test4 = test_citation_manager()
    test5 = test_handle_therapy_exists()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Test 1 (Imports): {'PASSED' if test1 else 'FAILED'}")
    print(f"Test 2 (Manager Init): {'PASSED' if test2 else 'FAILED'}")
    print(f"Test 3 (Profile Card): {'PASSED' if test3 else 'FAILED'}")
    print(f"Test 4 (Citation Manager): {'PASSED' if test4 else 'FAILED'}")
    print(f"Test 5 (_handle_therapy): {'PASSED' if test5 else 'FAILED'}")

    all_passed = test1 and test2 and test3 and test4 and test5

    if all_passed:
        print("\n>>> ALL PHASE 7 INTEGRATION TESTS PASSED!")
        print(">>> All therapy components properly integrated")
        print(">>> LLMResponseManager successfully refactored")
        print(">>> Ready for Phase 8 (UI implementation)")
    else:
        print("\n>>> SOME TESTS FAILED - review errors above")

    print("="*80)
