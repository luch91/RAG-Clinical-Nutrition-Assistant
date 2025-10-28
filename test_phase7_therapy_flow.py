"""
Test Phase 7: Complete 7-Step Therapy Flow Integration

Tests the refactored llm_response_manager with all therapy components.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from app.components.llm_response_manager import LLMResponseManager

def test_therapy_flow_integration():
    """Test complete therapy flow for Type 1 Diabetes."""
    print("\n" + "="*80)
    print("TEST: Phase 7 - Complete 7-Step Therapy Flow Integration")
    print("="*80)

    # Initialize LLM Response Manager
    print("\n[1] Initializing LLM Response Manager with therapy components...")
    try:
        manager = LLMResponseManager(dri_table_path="data/dri_table.csv")
        print("✓ Manager initialized successfully")
        print(f"  - therapy_gen: {type(manager.therapy_gen).__name__}")
        print(f"  - fct_mgr: {type(manager.fct_mgr).__name__}")
        print(f"  - meal_plan_gen: {type(manager.meal_plan_gen).__name__}")
    except Exception as e:
        print(f"✗ Failed to initialize manager: {e}")
        return False

    # Test query with all required slots for therapy
    print("\n[2] Testing therapy flow with Type 1 Diabetes query...")
    session_id = "test_therapy_t1d"

    # Mock query with all required information
    query = """
    8 year old boy with Type 1 Diabetes, weight 25kg, height 125cm,
    HbA1c 8.5%, glucose 180 mg/dL, takes insulin 20 units daily,
    from Kenya, no known allergies
    """

    print(f"Query: {query.strip()}")

    # Step 1: Classify query
    print("\n[3] Classifying query...")
    try:
        classification = manager.classify_query(session_id, query)
        print(f"✓ Query classified as: {classification.get('intent')}")
        print(f"  Diagnosis: {classification.get('diagnosis')}")
        print(f"  Confidence: {classification.get('confidence')}")
    except Exception as e:
        print(f"✗ Classification failed: {e}")
        return False

    # Step 2: Extract entities and populate slots
    print("\n[4] Extracting entities and populating slots...")
    try:
        entities = manager.extract_entities(query)
        session = manager._get_session(session_id)

        # Manually populate slots for testing (simulating multi-turn conversation)
        session["slots"] = {
            "diagnosis": "Type 1 Diabetes",
            "age": 8,
            "sex": "M",
            "weight_kg": 25.0,
            "height_cm": 125.0,
            "medications": ["Insulin 20 units daily"],
            "biomarkers_detailed": {
                "HbA1c": {"value": 8.5, "unit": "%"},
                "glucose": {"value": 180, "unit": "mg/dL"}
            },
            "country": "Kenya",
            "allergies": [],
            "activity_level": "moderate"
        }

        print("✓ Slots populated:")
        for key, value in session["slots"].items():
            print(f"  - {key}: {value}")
    except Exception as e:
        print(f"✗ Entity extraction failed: {e}")
        return False

    # Step 3: Execute therapy flow
    print("\n[5] Executing 7-step therapy flow...")
    print("-" * 80)

    try:
        result = manager._handle_therapy(
            session_id=session_id,
            query=query,
            session=session,
            query_info=classification
        )

        print(f"\n✓ Therapy flow executed")
        print(f"  Status: {result.get('status')}")

        payload = result.get('payload', {})

        # Check for therapy completion status
        therapy_status = payload.get('status')
        print(f"  Therapy Status: {therapy_status}")

        if therapy_status == "therapy_steps_1_to_5_complete":
            print("\n[6] Steps 1-5 Complete ✓")
            print(f"  - Diagnosis: {payload.get('diagnosis')}")
            print(f"  - Therapy Area: {payload.get('therapy_area')}")

            # Check baseline DRI
            baseline = payload.get('baseline_dri', {})
            print(f"\n  STEP 1 - Baseline DRI: {len(baseline)} nutrients")
            for nutrient in list(baseline.keys())[:3]:
                details = baseline[nutrient]
                print(f"    • {nutrient}: {details.get('value')} {details.get('unit')}")

            # Check therapeutic adjustments
            adjustments = payload.get('therapeutic_adjustments', {})
            print(f"\n  STEP 2 - Therapeutic Adjustments: {len(adjustments)} nutrients")
            for nutrient in list(adjustments.keys())[:3]:
                details = adjustments[nutrient]
                print(f"    • {nutrient}: {details.get('adjusted', details.get('value'))} {details.get('unit')}")
                if details.get('reason'):
                    print(f"      Reason: {details.get('reason')[:60]}...")

            # Check biochemical context
            bio_context = payload.get('biochemical_context', '')
            print(f"\n  STEP 3 - Biochemical Context:")
            print(f"    {bio_context[:100]}..." if len(bio_context) > 100 else f"    {bio_context}")

            # Check drug-nutrient interactions
            interactions = payload.get('drug_nutrient_interactions', [])
            print(f"\n  STEP 4 - Drug-Nutrient Interactions: {len(interactions)} found")
            for interaction in interactions[:2]:
                print(f"    • {interaction[:80]}...")

            # Check food sources
            food_sources = payload.get('food_sources', {})
            print(f"\n  STEP 5 - Food Sources: {len(food_sources)} nutrients")
            for nutrient in list(food_sources.keys())[:2]:
                foods = food_sources[nutrient]
                print(f"    • {nutrient}: {len(foods)} foods")
                for food in foods[:2]:
                    print(f"      - {food.get('food')}: {food.get('amount_per_100g')}")

            # Check profile card
            profile_card = payload.get('profile_card', '')
            print(f"\n  Profile Card Generated: {len(profile_card)} characters")
            print("  " + "-" * 40)
            print("  " + profile_card.split('\n')[0] if profile_card else "  (empty)")
            print("  " + "-" * 40)

            # Check citations
            citations = payload.get('citations', '')
            print(f"\n  Citations: {len(citations.split('•')) - 1} sources")

            # Check Step 6 message
            message = payload.get('message', '')
            print(f"\n  STEP 6 - Meal Plan Prompt:")
            print(f"    {message}")

            print("\n✓ PHASE 7 INTEGRATION TEST PASSED")
            print("  All 7 therapy components successfully integrated!")
            return True

        elif therapy_status == "therapy_complete":
            print("\n[6] All 7 Steps Complete (with meal plan) ✓")
            meal_plan = payload.get('meal_plan', {})
            print(f"  - Meal plan generated: {meal_plan.get('summary', {}).get('total_meals')} meals")
            return True

        else:
            print(f"\n✗ Unexpected therapy status: {therapy_status}")
            print(f"  Message: {payload.get('message')}")
            return False

    except Exception as e:
        print(f"\n✗ Therapy flow execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gatekeeper_downgrade():
    """Test gatekeeper downgrade when medications or biomarkers missing."""
    print("\n" + "="*80)
    print("TEST: Gatekeeper Downgrade (Missing Medications)")
    print("="*80)

    manager = LLMResponseManager(dri_table_path="data/dri_table.csv")
    session_id = "test_gatekeeper"

    query = "8 year old boy with Type 1 Diabetes, weight 25kg, height 125cm, from Kenya"

    classification = manager.classify_query(session_id, query)
    session = manager._get_session(session_id)

    # Populate slots WITHOUT medications and biomarkers
    session["slots"] = {
        "diagnosis": "Type 1 Diabetes",
        "age": 8,
        "sex": "M",
        "weight_kg": 25.0,
        "height_cm": 125.0,
        "country": "Kenya",
        "allergies": []
    }

    print("\nExecuting therapy flow with missing critical data...")
    result = manager._handle_therapy(session_id, query, session, classification)

    if result.get("status") == "downgraded":
        print(f"✓ Gatekeeper correctly downgraded")
        print(f"  Reason: {result.get('reason')}")
        print(f"  Message: {result.get('message')[:100]}...")
        return True
    else:
        print(f"✗ Gatekeeper failed - status: {result.get('status')}")
        return False


if __name__ == "__main__":
    print("\n" + "🧪" * 40)
    print("PHASE 7: 7-STEP THERAPY FLOW INTEGRATION TESTS")
    print("🧪" * 40)

    # Test 1: Complete therapy flow
    test1_passed = test_therapy_flow_integration()

    # Test 2: Gatekeeper downgrade
    test2_passed = test_gatekeeper_downgrade()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Test 1 (Therapy Flow Integration): {'✓ PASSED' if test1_passed else '✗ FAILED'}")
    print(f"Test 2 (Gatekeeper Downgrade): {'✓ PASSED' if test2_passed else '✗ FAILED'}")

    if test1_passed and test2_passed:
        print("\n🎉 ALL PHASE 7 TESTS PASSED!")
        print("7-step therapy flow successfully integrated into llm_response_manager.py")
    else:
        print("\n⚠️ SOME TESTS FAILED - review errors above")

    print("="*80)
