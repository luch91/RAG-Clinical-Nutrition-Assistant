"""
Synchronicity Check - Verify Phase 7 didn't break Phases 1-6

Quick tests to verify all components work together without broken imports or dependencies.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_all_imports():
    """Test that all components can be imported without errors."""
    print("\n" + "="*80)
    print("TEST 1: All Component Imports (Phases 1-7)")
    print("="*80)

    try:
        # Phase 1-2: Configuration and data layer
        from app.config.therapeutic_nutrients import THERAPEUTIC_NUTRIENTS
        from app.config.fct_country_mapping import COUNTRY_TO_FCT
        print("[OK] Phase 1 configs imported")

        from app.components.dri_loader import DRILoader
        from app.components.metadata_enricher import MetadataEnricher
        print("[OK] Phase 2 data layer imported")

        # Phase 3: Core components
        from app.components.query_classifier import NutritionQueryClassifier
        from app.components.computation_manager import ComputationManager
        from app.components.followup_question_generator import FollowUpQuestionGenerator
        print("[OK] Phase 3 core components imported")

        # Phase 4: Retrieval
        from app.components.hybrid_retriever import filtered_retrieval
        from app.components.fct_manager import FCTManager
        print("[OK] Phase 4 retrieval components imported")

        # Phase 5: Therapy core
        from app.components.therapy_generator import TherapyGenerator
        print("[OK] Phase 5 therapy generator imported")

        # Phase 6: Meal planning
        from app.components.meal_plan_generator import MealPlanGenerator
        print("[OK] Phase 6 meal planner imported")

        # Phase 7: Orchestration
        from app.components.llm_response_manager import LLMResponseManager
        from app.components.citation_manager import CitationManager
        from app.components.profile_summary_card import ProfileSummaryCard
        print("[OK] Phase 7 orchestration imported")

        print("\n[SUCCESS] All components imported successfully - No broken imports!")
        return True

    except Exception as e:
        print(f"\n[FAIL] Import error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_component_initialization():
    """Test that all components can be initialized."""
    print("\n" + "="*80)
    print("TEST 2: Component Initialization")
    print("="*80)

    try:
        from app.components.llm_response_manager import LLMResponseManager

        print("\nInitializing LLMResponseManager...")
        manager = LLMResponseManager(dri_table_path="data/dri_table.csv")

        # Check all expected components exist
        components = {
            "classifier": "NutritionQueryClassifier",
            "followup_gen": "FollowUpQuestionGenerator",
            "computation": "ComputationManager",
            "therapy_gen": "TherapyGenerator",
            "fct_mgr": "FCTManager",
            "meal_plan_gen": "MealPlanGenerator"
        }

        all_present = True
        for attr, expected_type in components.items():
            if hasattr(manager, attr):
                actual_type = type(getattr(manager, attr)).__name__
                print(f"[OK] {attr}: {actual_type}")
                if actual_type != expected_type:
                    print(f"  [WARN] Expected {expected_type}, got {actual_type}")
            else:
                print(f"[FAIL] {attr} not found")
                all_present = False

        if all_present:
            print("\n[SUCCESS] All components initialized correctly!")
            return True
        else:
            print("\n[FAIL] Some components missing")
            return False

    except Exception as e:
        print(f"\n[FAIL] Initialization error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dri_loader_phase1_methods():
    """Test Phase 1 DRILoader methods still work."""
    print("\n" + "="*80)
    print("TEST 3: DRILoader Phase 1 Methods")
    print("="*80)

    try:
        from app.components.dri_loader import DRILoader

        dri = DRILoader(csv_path="data/dri_table.csv")

        # Test get_dri_baseline_for_therapy (Phase 1)
        print("\nTesting get_dri_baseline_for_therapy()...")
        baseline = dri.get_dri_baseline_for_therapy(age=8, sex="M")

        if baseline and isinstance(baseline, dict):
            print(f"[OK] Returned {len(baseline)} nutrients")
            # Check a few expected nutrients
            expected = ["protein", "energy", "calcium", "iron"]
            found = [n for n in expected if n in baseline]
            print(f"  Expected nutrients found: {found}")

            if len(found) == len(expected):
                print("[SUCCESS] DRILoader Phase 1 methods work!")
                return True
            else:
                print(f"[FAIL] Missing nutrients: {set(expected) - set(found)}")
                return False
        else:
            print("[FAIL] Invalid return value")
            return False

    except Exception as e:
        print(f"\n[FAIL] DRILoader test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_computation_manager_integration():
    """Test ComputationManager works with Phase 7."""
    print("\n" + "="*80)
    print("TEST 4: ComputationManager Integration")
    print("="*80)

    try:
        from app.components.computation_manager import ComputationManager

        comp = ComputationManager(dri_table_path="data/dri_table.csv")

        # Test get_dri_baseline_with_energy (used in Phase 7)
        print("\nTesting get_dri_baseline_with_energy()...")
        result = comp.get_dri_baseline_with_energy(
            age=8, sex="M", weight_kg=25, height_cm=125, activity_level="moderate"
        )

        if result and isinstance(result, dict):
            print(f"[OK] Returned {len(result)} nutrients with energy")

            # Check energy is included
            if "energy" in result:
                energy_val = result["energy"].get("value")
                print(f"  Energy: {energy_val} kcal")
                print("[SUCCESS] ComputationManager integration works!")
                return True
            else:
                print("[FAIL] Energy not in result")
                return False
        else:
            print("[FAIL] Invalid return value")
            return False

    except Exception as e:
        print(f"\n[FAIL] ComputationManager test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_therapy_generator_methods():
    """Test TherapyGenerator methods (Phase 5)."""
    print("\n" + "="*80)
    print("TEST 5: TherapyGenerator Methods (Phase 5)")
    print("="*80)

    try:
        from app.components.therapy_generator import TherapyGenerator

        therapy_gen = TherapyGenerator()
        print("[OK] TherapyGenerator initialized")

        # Check methods exist
        methods = [
            "get_therapeutic_adjustments",
            "get_biochemical_context",
            "calculate_drug_nutrient_interactions"
        ]

        all_exist = True
        for method in methods:
            if hasattr(therapy_gen, method):
                print(f"[OK] Method '{method}' exists")
            else:
                print(f"[FAIL] Method '{method}' missing")
                all_exist = False

        if all_exist:
            print("\n[SUCCESS] TherapyGenerator has all required methods!")
            return True
        else:
            print("\n[FAIL] Some methods missing")
            return False

    except Exception as e:
        print(f"\n[FAIL] TherapyGenerator test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fct_manager_integration():
    """Test FCTManager (Phase 4)."""
    print("\n" + "="*80)
    print("TEST 6: FCTManager Integration (Phase 4)")
    print("="*80)

    try:
        from app.components.fct_manager import FCTManager

        fct_mgr = FCTManager()
        print("[OK] FCTManager initialized")

        # Test get_fct_for_country
        print("\nTesting get_fct_for_country()...")
        kenya_fct = fct_mgr.get_fct_for_country("Kenya")

        if kenya_fct:
            print(f"[OK] Kenya FCT path: {kenya_fct}")
            print("[SUCCESS] FCTManager integration works!")
            return True
        else:
            print("[FAIL] No FCT path returned")
            return False

    except Exception as e:
        print(f"\n[FAIL] FCTManager test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_meal_plan_generator():
    """Test MealPlanGenerator (Phase 6)."""
    print("\n" + "="*80)
    print("TEST 7: MealPlanGenerator (Phase 6)")
    print("="*80)

    try:
        from app.components.meal_plan_generator import MealPlanGenerator

        meal_gen = MealPlanGenerator()
        print("[OK] MealPlanGenerator initialized")

        # Check methods exist
        methods = ["generate_3day_plan", "format_meal_plan_for_display"]

        all_exist = True
        for method in methods:
            if hasattr(meal_gen, method):
                print(f"[OK] Method '{method}' exists")
            else:
                print(f"[FAIL] Method '{method}' missing")
                all_exist = False

        if all_exist:
            print("\n[SUCCESS] MealPlanGenerator has all required methods!")
            return True
        else:
            print("\n[FAIL] Some methods missing")
            return False

    except Exception as e:
        print(f"\n[FAIL] MealPlanGenerator test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_citation_and_profile_card():
    """Test CitationManager and ProfileSummaryCard (Phase 7)."""
    print("\n" + "="*80)
    print("TEST 8: CitationManager & ProfileSummaryCard (Phase 7)")
    print("="*80)

    try:
        from app.components.citation_manager import CitationManager
        from app.components.profile_summary_card import ProfileSummaryCard

        # Test CitationManager
        citations = CitationManager()
        citations.add_citation("Test Source", context="Test context")
        formatted = citations.get_grouped_citations()

        if formatted and len(formatted) > 0:
            print("[OK] CitationManager works")
        else:
            print("[FAIL] CitationManager empty result")
            return False

        # Test ProfileSummaryCard
        patient_info = {
            "age": 8, "sex": "M", "diagnosis": "Type 1 Diabetes",
            "weight_kg": 25, "height_cm": 125
        }
        card = ProfileSummaryCard.initialize_card(patient_info)
        display = card.format_for_display()

        if display and len(display) > 0:
            print("[OK] ProfileSummaryCard works")
            print("\n[SUCCESS] Citation & Profile Card work!")
            return True
        else:
            print("[FAIL] ProfileSummaryCard empty display")
            return False

    except Exception as e:
        print(f"\n[FAIL] Citation/Profile test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_handle_therapy_signature():
    """Test _handle_therapy method signature is correct."""
    print("\n" + "="*80)
    print("TEST 9: _handle_therapy Method Signature")
    print("="*80)

    try:
        from app.components.llm_response_manager import LLMResponseManager
        import inspect

        manager = LLMResponseManager(dri_table_path="data/dri_table.csv")

        if not hasattr(manager, '_handle_therapy'):
            print("[FAIL] _handle_therapy method not found")
            return False

        sig = inspect.signature(manager._handle_therapy)
        params = list(sig.parameters.keys())

        expected = ['session_id', 'query', 'session', 'query_info']

        if params == expected:
            print(f"[OK] Signature correct: {', '.join(params)}")
            print("[SUCCESS] _handle_therapy signature is correct!")
            return True
        else:
            print(f"[FAIL] Expected: {expected}")
            print(f"[FAIL] Got: {params}")
            return False

    except Exception as e:
        print(f"\n[FAIL] Signature test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "="*80)
    print("SYNCHRONICITY CHECK - PHASES 1-7")
    print("Verify Phase 7 didn't break existing components")
    print("="*80)

    tests = [
        ("All Imports", test_all_imports),
        ("Component Initialization", test_component_initialization),
        ("DRILoader Phase 1", test_dri_loader_phase1_methods),
        ("ComputationManager Integration", test_computation_manager_integration),
        ("TherapyGenerator Methods", test_therapy_generator_methods),
        ("FCTManager Integration", test_fct_manager_integration),
        ("MealPlanGenerator", test_meal_plan_generator),
        ("Citation & Profile Card", test_citation_and_profile_card),
        ("_handle_therapy Signature", test_handle_therapy_signature)
    ]

    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n[ERROR] Test '{test_name}' crashed: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results:
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name}: {status}")

    total = len(results)
    passed_count = sum(1 for _, p in results if p)

    print(f"\nTotal: {passed_count}/{total} tests passed ({100*passed_count//total}%)")

    if passed_count == total:
        print("\n>>> ALL SYNCHRONICITY CHECKS PASSED!")
        print(">>> Phase 7 integration is successful - no broken code!")
    else:
        print(f"\n>>> {total - passed_count} TESTS FAILED")
        print(">>> Some components need attention")

    print("="*80)
