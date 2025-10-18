import os
import requests
from tenacity import retry, stop_after_attempt, wait_fixed, RetryError
from huggingface_hub import InferenceClient
from langchain_core.language_models.llms import LLM
from langchain_core.callbacks import CallbackManagerForLLMRun
from typing import Optional, List, Dict, Any, Union
from pydantic import Field
from app.common.logger import get_logger
from app.common.custom_exception import CustomException
from app.common.circuit_breaker import get_together_breaker, get_huggingface_breaker, CircuitBreakerError
from app.config.config import (
    TOGETHER_API_KEY,
    HUGGINGFACE_API_KEY,
    API_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY
)

logger = get_logger(__name__)

class HuggingFaceLLM(LLM):
    """LangChain-compatible wrapper for Hugging Face models using InferenceClient"""
    repo_id: str = Field(default="google/gemma-2-2b-it")
    task: str = Field(default="text-generation")
    model_kwargs: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "huggingface_hub"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Generate text from the model with circuit breaker protection"""
        breaker = get_huggingface_breaker()

        def _execute():
            client = InferenceClient(
                model=self.repo_id,
                token=HUGGINGFACE_API_KEY or os.getenv("HUGGINGFACE_API_KEY")
            )
            response = client.text_generation(
                prompt,
                max_new_tokens=512,
                temperature=0.7,
                **self.model_kwargs
            )
            return response

        try:
            return breaker.call(_execute)
        except CircuitBreakerError as e:
            logger.error(f"Circuit breaker OPEN for HuggingFace: {str(e)}")
            raise CustomException("HuggingFace API temporarily unavailable", e)
        except Exception as e:
            logger.error(f"Hugging Face model '{self.repo_id}' failed: {str(e)}")
            raise CustomException("Hugging Face model failed", e)

class TogetherLLM(LLM):
    """LangChain-compatible wrapper for Together models"""
    model_name: str = Field(default="deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free")
    api_key: str = Field(default_factory=lambda: TOGETHER_API_KEY or os.getenv("TOGETHER_API_KEY"))
    
    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "together"

    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(RETRY_DELAY))
    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Generate text from the model with circuit breaker protection"""
        breaker = get_together_breaker()

        def _execute():
            url = "https://api.together.xyz/v1/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "max_tokens": 512,
                "temperature": 0.7,
                **kwargs
            }
            response = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0].get("text", "").strip()
            elif "output" in result:
                return result["output"].strip()
            else:
                raise CustomException(f"Unexpected Together API response: {result}")

        try:
            return breaker.call(_execute)
        except CircuitBreakerError as e:
            logger.error(f"Circuit breaker OPEN for Together API: {str(e)}")
            raise CustomException("Together API temporarily unavailable", e)
        except Exception as e:
            logger.warning(f"Together API failed: {str(e)}. Will retry or fall back.")
            raise

def get_llm_client(model_name: str = None) -> LLM:
    """
    Factory function to initialize and return a LangChain-compatible LLM.
    Maps template keys to appropriate models per acceptance criteria:
    - therapy → DeepSeek-R1-Distill-Llama-70B (powerful, clinical reasoning)
    - general, comparison, recommendation → Llama-3.2-3B (fast, cost-effective)
    """
    # Map template keys to model configurations — STRICTLY ENFORCED
    MODEL_MAP = {
        # THERAPY: DeepSeek-R1 (powerful reasoning for medical therapy) via Together AI
        "therapy": {"provider": "together", "model": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free"},

        # ALL OTHERS: Llama-3.2-3B via Together AI (fast, reliable)
        # Fallback to HuggingFace if Together fails
        "general": {"provider": "together", "model": "meta-llama/Llama-3.2-3B-Instruct-Turbo"},
        "comparison": {"provider": "together", "model": "meta-llama/Llama-3.2-3B-Instruct-Turbo"},
        "recommendation": {"provider": "together", "model": "meta-llama/Llama-3.2-3B-Instruct-Turbo"},
        # Legacy categories (deprecated, kept for backward compatibility)
        "dermatology": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "renal": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "diabetes": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "vegetarian": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "allergy": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "sports": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "pregnancy": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "lactation": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "pediatric": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "geriatrics": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "cardiac": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "gastro": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "nutrigenomics": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "genetic_risk": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "iron_deficiency": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "zinc_deficiency": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "calcium_deficiency": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "post_surgical": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "weight_loss": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "cancer": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
        "IEM": {"provider": "huggingface", "model": "google/gemma-2-2b-it"},
    }

    # Get default strategy from config if no model_name provided
    if model_name is None:
        from app.config.config import DEFAULT_MODEL_STRATEGY
        model_name = DEFAULT_MODEL_STRATEGY

    # Determine provider and model
    config = MODEL_MAP.get(model_name, MODEL_MAP["general"])
    provider = config["provider"]
    model_id = config["model"]
    logger.info(f"Using {provider} provider with model: {model_id}")

    # Create appropriate LLM instance - ALWAYS TRY TOGETHER AI FIRST
    try:
        if not TOGETHER_API_KEY and not os.getenv("TOGETHER_API_KEY"):
            logger.warning("⚠️ No Together API key found. Will try HuggingFace fallback.")
            raise ValueError("No Together API key")

        # Try Together AI
        return TogetherLLM(model_name=model_id)
    except Exception as e:
        logger.warning(f"Together AI failed: {str(e)}. Trying HuggingFace fallback.")

    # Fallback to Hugging Face with Llama
    try:
        if not HUGGINGFACE_API_KEY and not os.getenv("HUGGINGFACE_API_KEY"):
            logger.warning("⚠️ No Hugging Face API key found. Using free tier limitations.")

        # Use Llama 3.2 3B for fallback (better than Gemma)
        fallback_model = "meta-llama/Llama-3.2-3B-Instruct"
        logger.warning(f"⚠️ Falling back to HuggingFace {fallback_model} for intent: {model_name}")
        return HuggingFaceLLM(repo_id=fallback_model)
    except Exception as e:
        logger.error(f"Both LLM providers failed: {str(e)}")
        # Final fallback — echo with disclaimer
        class EchoLLM(LLM):
            @property
            def _llm_type(self) -> str:
                return "echo"
            def _call(
                self,
                prompt: str,
                stop: Optional[List[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None,
                **kwargs: Any,
            ) -> str:
                return (
                    "⚠️ System error: I'm currently experiencing technical difficulties. "
                    "Please try again later or contact support if the issue persists. "
                    "For educational purposes only. Not medical advice. Consult a healthcare provider."
                )
        return EchoLLM()

# Backward compatibility for existing imports
class HuggingFaceLLMClient:
    """Backward compatibility class for existing imports"""
    def __init__(self, model_name: str = "default"):
        self.model_name = model_name
        self.llm = get_llm_client(model_name)
    
    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 512) -> str:
        """Generate text using the LLM"""
        try:
            return self.llm.invoke(prompt, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            return (
                "⚠️ System error: I encountered an issue while processing your request. "
                "Please try again later. For educational purposes only. Not medical advice. Consult a healthcare provider."
            )

# Verify the module is properly initialized
try:
    test_client = get_llm_client("general")
    logger.info("✅ api_models.py initialized successfully with LangChain-compatible LLMs")
except Exception as e:
    logger.error(f"❌ Critical error in api_models.py: {str(e)}")
    logger.warning("⚠️ api_models.py initialized with fallback implementations")