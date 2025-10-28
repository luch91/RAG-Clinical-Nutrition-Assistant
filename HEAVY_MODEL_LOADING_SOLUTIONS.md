# Solutions for Heavy Model Loading Issue

## Problem

**Current Behavior:**
- DistilBERT model takes ~1.5 minutes to load (see test output: 2025-10-28 03:23:48 → 03:25:35 = 107 seconds)
- Tests timeout before completion
- Slows down development and CI/CD

**Root Cause:**
```python
# app/components/query_classifier.py line 116
self.classifier = NutritionQueryClassifier()  # Loads DistilBERT model
```

---

## Solutions (Ordered by Recommendation)

### ✅ **Solution 1: Lazy Loading (Recommended - Fastest Implementation)**

**Impact:** Reduces test time from 107s to <1s for tests that don't need classification

**Implementation:**

```python
# app/components/llm_response_manager.py

class LLMResponseManager:
    def __init__(self, dri_table_path: str = "data/dri_table.csv"):
        # Core components
        self._classifier = None  # Lazy load
        self.followup_gen = FollowUpQuestionGenerator()
        self.computation = ComputationManager(dri_table_path)

        # Therapy flow components
        self.therapy_gen = TherapyGenerator()
        self.fct_mgr = FCTManager()
        self.meal_plan_gen = MealPlanGenerator()

        # ... rest of init ...

    @property
    def classifier(self):
        """Lazy load classifier only when needed."""
        if self._classifier is None:
            logger.info("Loading classifier model (first access)...")
            from app.components.query_classifier import NutritionQueryClassifier
            self._classifier = NutritionQueryClassifier()
        return self._classifier
```

**Pros:**
- ✅ Simple to implement (~5 lines of code)
- ✅ No breaking changes to existing code
- ✅ Tests that don't use classifier run instantly
- ✅ Production behavior unchanged (still loads on first use)

**Cons:**
- ⚠️ First query still has 107s delay
- ⚠️ Not suitable if every query needs classification

**Use Case:** Tests, development, microservices that may not need classification

---

### ✅ **Solution 2: Model Caching with Singleton Pattern (Recommended - Production)**

**Impact:** Model loads once per process, all subsequent loads instant

**Implementation:**

```python
# app/components/query_classifier.py

class NutritionQueryClassifier:
    _model_cache = None  # Class-level cache
    _tokenizer_cache = None
    _cache_lock = threading.Lock()

    def __init__(self):
        with self._cache_lock:  # Thread-safe
            if NutritionQueryClassifier._model_cache is None:
                logger.info("Loading model for first time...")
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    DISTILBERT_CLASSIFIER_PATH
                )
                self.tokenizer = AutoTokenizer.from_pretrained(
                    DISTILBERT_CLASSIFIER_PATH
                )
                # Cache for reuse
                NutritionQueryClassifier._model_cache = self.model
                NutritionQueryClassifier._tokenizer_cache = self.tokenizer
            else:
                logger.info("Using cached model (instant load)")
                self.model = NutritionQueryClassifier._model_cache
                self.tokenizer = NutritionQueryClassifier._tokenizer_cache
```

**Pros:**
- ✅ First load: 107s, all subsequent: <1s
- ✅ Works across multiple LLMResponseManager instances
- ✅ Thread-safe
- ✅ Production-ready

**Cons:**
- ⚠️ Memory stays allocated for process lifetime
- ⚠️ First load still slow (but only once per process)

**Use Case:** Production, Flask server, long-running processes

---

### ✅ **Solution 3: Preload Model on App Startup (Best for Production)**

**Impact:** Load model once at startup, all queries instant

**Implementation:**

```python
# app/app.py (Flask backend)

from app.components.query_classifier import NutritionQueryClassifier

# Preload model at startup
logger.info("Preloading DistilBERT model...")
_preloaded_classifier = NutritionQueryClassifier()
logger.info("Model preloaded successfully!")

# Use in LLMResponseManager
class LLMResponseManager:
    def __init__(self, dri_table_path: str = "data/dri_table.csv",
                 preloaded_classifier=None):
        # Use preloaded classifier if available
        self.classifier = preloaded_classifier or NutritionQueryClassifier()
        # ... rest of init ...

# In Flask routes
llm_manager = LLMResponseManager(
    dri_table_path="data/dri_table.csv",
    preloaded_classifier=_preloaded_classifier  # Reuse
)
```

**Pros:**
- ✅ All user queries instant (no waiting)
- ✅ Best user experience
- ✅ Model loaded once at startup
- ✅ Production-ready

**Cons:**
- ⚠️ Startup time increases by 107s
- ⚠️ Memory always allocated
- ⚠️ Requires app restart to reload model

**Use Case:** Production Flask/FastAPI server, Gradio UI

---

### ✅ **Solution 4: Use Smaller/Faster Model (Long-term)**

**Impact:** Reduce load time from 107s to ~10-20s

**Implementation:**

**Option A: DistilBERT Quantization**
```python
# Quantize model to INT8 (4x smaller, 2-3x faster)
from transformers import AutoModelForSequenceClassification
import torch

model = AutoModelForSequenceClassification.from_pretrained(
    DISTILBERT_CLASSIFIER_PATH
)

# Quantize to INT8
quantized_model = torch.quantization.quantize_dynamic(
    model, {torch.nn.Linear}, dtype=torch.qint8
)

# Save quantized model
quantized_model.save_pretrained("models/distilbert-quantized")
```

**Option B: Switch to TinyBERT/MobileBERT**
- TinyBERT: 4x smaller, 3x faster
- MobileBERT: 4x smaller, similar speed
- Trade-off: Slightly lower accuracy (~2-3%)

**Pros:**
- ✅ Faster load time (10-20s vs 107s)
- ✅ Lower memory usage
- ✅ Faster inference

**Cons:**
- ⚠️ Requires model retraining/fine-tuning
- ⚠️ Potential accuracy loss
- ⚠️ Time-consuming implementation

**Use Case:** Long-term optimization, resource-constrained environments

---

### ✅ **Solution 5: Mock Classifier for Tests (Testing Only)**

**Impact:** Tests run in <1s with mock classification

**Implementation:**

```python
# tests/conftest.py (pytest fixture)

import pytest
from unittest.mock import Mock

@pytest.fixture
def mock_classifier():
    """Mock classifier for fast tests."""
    classifier = Mock()
    classifier.classify.return_value = {
        "intent": "therapy",
        "confidence": 0.95,
        "diagnosis": "Type 1 Diabetes"
    }
    return classifier

# In tests
def test_therapy_flow(mock_classifier):
    manager = LLMResponseManager(dri_table_path="data/dri_table.csv")
    manager.classifier = mock_classifier  # Replace with mock

    # Test runs instantly
    result = manager.classify_query("test_session", "test query")
    assert result["intent"] == "therapy"
```

**Pros:**
- ✅ Tests run in <1s
- ✅ No model loading needed
- ✅ Deterministic test results
- ✅ Easy to implement

**Cons:**
- ⚠️ Not testing real classifier
- ⚠️ Only for unit tests, not integration tests

**Use Case:** Unit tests, CI/CD, rapid development

---

### ✅ **Solution 6: Increase Test Timeout (Quick Fix)**

**Impact:** Tests complete successfully (but still slow)

**Implementation:**

```python
# test_critical_gatekeeper.py

# Change timeout from 30s to 180s
timeout 180 python test_critical_gatekeeper.py
```

**Pros:**
- ✅ Immediate fix (no code changes)
- ✅ Tests complete successfully

**Cons:**
- ⚠️ Still slow (3 minutes per test run)
- ⚠️ Not a real solution

**Use Case:** Quick fix while implementing proper solution

---

## Recommended Implementation Strategy

### **Phase 1: Immediate (Now)**
1. **Increase test timeouts to 180s** (Solution 6)
   - Quick fix to make tests pass
   - No code changes needed
   - Buys time for proper solution

2. **Add mock classifier for unit tests** (Solution 5)
   - Fast unit tests for development
   - Keep integration tests with real classifier

### **Phase 2: Next Session (Phase 8)**
3. **Implement lazy loading** (Solution 1)
   - Simple, non-breaking change
   - Tests that don't need classifier run fast
   - Production still works

4. **Implement singleton pattern** (Solution 2)
   - Production optimization
   - Model loaded once per process
   - Thread-safe caching

### **Phase 3: Production Deployment**
5. **Preload model at startup** (Solution 3)
   - Best user experience
   - Flask app loads model once at startup
   - All user queries instant

### **Phase 4: Long-term Optimization (Optional)**
6. **Model quantization** (Solution 4)
   - Reduce load time from 107s to ~20s
   - Lower memory usage
   - Requires testing for accuracy impact

---

## Implementation Priority

### **Critical (Do Now):**
- ✅ **Solution 6: Increase timeouts** → Immediate fix

### **High Priority (Phase 8):**
- ✅ **Solution 5: Mock classifier for tests** → Fast development
- ✅ **Solution 3: Preload on startup** → Best production UX

### **Medium Priority (Post-Phase 8):**
- ⚠️ **Solution 2: Singleton caching** → Production optimization
- ⚠️ **Solution 1: Lazy loading** → Development optimization

### **Low Priority (Future):**
- 🔵 **Solution 4: Smaller model** → Long-term optimization

---

## Code Changes Required

### **Immediate: Increase Timeouts**

```bash
# Update all test commands
timeout 180 python test_critical_gatekeeper.py
timeout 180 python test_cross_phase_validation.py
timeout 180 python test_synchronicity_check.py
```

**Effort:** 1 minute
**Impact:** Tests pass immediately

---

### **Phase 8: Preload Model in Flask**

```python
# app/app.py

from app.components.query_classifier import NutritionQueryClassifier
import logging

logger = logging.getLogger(__name__)

# Preload model at startup
logger.info("=" * 80)
logger.info("PRELOADING MODELS...")
logger.info("=" * 80)

_preloaded_classifier = NutritionQueryClassifier()

logger.info("Model preloaded successfully!")
logger.info("=" * 80)

# Update LLMResponseManager initialization
llm_manager = LLMResponseManager(
    dri_table_path="data/dri_table.csv",
    preloaded_classifier=_preloaded_classifier
)
```

```python
# app/components/llm_response_manager.py

class LLMResponseManager:
    def __init__(self, dri_table_path: str = "data/dri_table.csv",
                 preloaded_classifier=None):
        # Use preloaded classifier if available
        if preloaded_classifier:
            logger.info("Using preloaded classifier (instant)")
            self.classifier = preloaded_classifier
        else:
            logger.info("Loading classifier (first time)")
            self.classifier = NutritionQueryClassifier()

        # ... rest unchanged ...
```

**Effort:** 10 minutes
**Impact:** All user queries instant after startup

---

## Monitoring Model Load Time

Add timing to understand the issue:

```python
# app/components/query_classifier.py

import time

def __init__(self):
    start_time = time.time()
    logger.info("Loading DistilBERT classifier...")

    self.model = AutoModelForSequenceClassification.from_pretrained(
        DISTILBERT_CLASSIFIER_PATH
    )
    self.tokenizer = AutoTokenizer.from_pretrained(
        DISTILBERT_CLASSIFIER_PATH
    )

    load_time = time.time() - start_time
    logger.info(f"Classifier loaded in {load_time:.2f} seconds")
```

This will help identify if the issue gets worse over time.

---

## Summary

**Immediate Action (Now):**
- Increase test timeouts to 180s ✅

**Phase 8 Implementation:**
- Preload model in Flask app ✅
- Add optional preloaded_classifier parameter to LLMResponseManager ✅

**Future Optimizations:**
- Singleton pattern caching
- Model quantization
- Mock classifier for unit tests

**Expected Results:**
- Tests: Pass (with 180s timeout)
- Production: Instant queries (after startup preload)
- Development: Fast iteration (with mocks)
