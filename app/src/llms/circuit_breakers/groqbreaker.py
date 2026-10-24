
import asyncio
import time
from dataclasses import dataclass
from enum import Enum

from app.src.core.config import Settings


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when Groq calls are temporarily blocked."""


@dataclass(frozen=True)
class CircuitPermit:
    epoch: int
    is_probe: bool


class GroqCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = Settings().GROQ_FAILURE_THRESHOLD,
        recovery_timeout: float = Settings().GROQ_RECOVERY_TIMEOUT,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

        self._epoch = 0
        self._probe_in_progress = False
        self._lock = asyncio.Lock()

    async def before_request(self) -> CircuitPermit:
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return CircuitPermit(self._epoch, False)

            if self.state == CircuitState.OPEN:
                elapsed = time.monotonic() - self.last_failure_time

                if elapsed < self.recovery_timeout:
                    raise CircuitBreakerOpenError(
                        "Groq is temporarily unavailable"
                    )

                self.state = CircuitState.HALF_OPEN

            if self._probe_in_progress:
                raise CircuitBreakerOpenError(
                    "Groq recovery probe is already running"
                )

            self._probe_in_progress = True
            return CircuitPermit(self._epoch, True)

    async def record_success(self, permit: CircuitPermit) -> None:
        async with self._lock:
            if permit.epoch != self._epoch:
                return

            if permit.is_probe:
                if self.state != CircuitState.HALF_OPEN:
                    return

                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.last_failure_time = None
                self._probe_in_progress = False
                self._epoch += 1
                return

            if self.state == CircuitState.CLOSED:
                self.failure_count = 0

    async def record_failure(self, permit: CircuitPermit) -> None:
        async with self._lock:
            if permit.epoch != self._epoch:
                return

            if permit.is_probe:
                if self.state != CircuitState.HALF_OPEN:
                    return

                self.state = CircuitState.OPEN
                self.last_failure_time = time.monotonic()
                self._probe_in_progress = False
                self._epoch += 1
                return

            if self.state != CircuitState.CLOSED:
                return

            self.failure_count += 1

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_failure_time = time.monotonic()
                self._epoch += 1

    async def abandon(self, permit: CircuitPermit) -> None:
        """Release a cancelled recovery probe without counting a failure."""
        async with self._lock:
            if permit.epoch != self._epoch:
                return

            if permit.is_probe and self.state == CircuitState.HALF_OPEN:
                self._probe_in_progress = False
                self.state = CircuitState.OPEN
                self.last_failure_time = time.monotonic()
                self._epoch += 1


groq_circuit_breaker = GroqCircuitBreaker()
