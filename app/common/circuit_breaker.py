# app/common/circuit_breaker.py
"""
Circuit breaker pattern for external API calls.
Prevents cascading failures when external services are down.
"""
import time
import threading
from enum import Enum
from typing import Callable, Any, Optional
from app.common.logger import get_logger

logger = get_logger(__name__)

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    """
    Circuit breaker for external API calls.

    Args:
        failure_threshold: Number of failures before opening circuit
        success_threshold: Number of successes needed to close circuit
        timeout: Seconds to wait before moving to HALF_OPEN
        name: Name of the circuit (for logging)
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: int = 60,
        name: str = "unnamed"
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.name = name

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.lock = threading.RLock()

        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={failure_threshold}, timeout={timeout}s"
        )

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Raises:
            CircuitBreakerError: If circuit is OPEN
        """
        with self.lock:
            # Check if we should transition to HALF_OPEN
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.timeout:
                    logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    # Circuit still open, reject request
                    logger.warning(
                        f"Circuit breaker '{self.name}' is OPEN, rejecting request"
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Retry after {int(self.timeout - (time.time() - self.last_failure_time))}s"
                    )

        # Try to execute the function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call"""
        with self.lock:
            self.failure_count = 0

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    logger.info(f"Circuit breaker '{self.name}' closing (recovered)")
                    self.state = CircuitState.CLOSED
                    self.success_count = 0

    def _on_failure(self):
        """Handle failed call"""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                logger.warning(f"Circuit breaker '{self.name}' opening (test failed)")
                self.state = CircuitState.OPEN
                self.success_count = 0
            elif self.failure_count >= self.failure_threshold:
                logger.error(
                    f"Circuit breaker '{self.name}' opening "
                    f"(failures: {self.failure_count}/{self.failure_threshold})"
                )
                self.state = CircuitState.OPEN

    def reset(self):
        """Manually reset circuit breaker to CLOSED state"""
        with self.lock:
            logger.info(f"Circuit breaker '{self.name}' manually reset")
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None

    def get_status(self) -> dict:
        """Get current circuit breaker status"""
        with self.lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_time": self.last_failure_time,
            }

class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""
    pass

# Pre-configured circuit breakers for different services
class CircuitBreakers:
    """Global circuit breakers for external services"""
    _lock = threading.Lock()
    _breakers = {}

    @classmethod
    def get_breaker(cls, name: str, **kwargs) -> CircuitBreaker:
        """Get or create a circuit breaker by name"""
        with cls._lock:
            if name not in cls._breakers:
                cls._breakers[name] = CircuitBreaker(name=name, **kwargs)
            return cls._breakers[name]

    @classmethod
    def reset_all(cls):
        """Reset all circuit breakers"""
        with cls._lock:
            for breaker in cls._breakers.values():
                breaker.reset()

# Pre-configured breakers
def get_together_breaker() -> CircuitBreaker:
    """Get circuit breaker for Together API"""
    return CircuitBreakers.get_breaker(
        "together_api",
        failure_threshold=5,
        success_threshold=2,
        timeout=60
    )

def get_huggingface_breaker() -> CircuitBreaker:
    """Get circuit breaker for HuggingFace API"""
    return CircuitBreakers.get_breaker(
        "huggingface_api",
        failure_threshold=5,
        success_threshold=2,
        timeout=60
    )

def get_rxnorm_breaker() -> CircuitBreaker:
    """Get circuit breaker for RxNorm API"""
    return CircuitBreakers.get_breaker(
        "rxnorm_api",
        failure_threshold=3,
        success_threshold=1,
        timeout=30
    )
