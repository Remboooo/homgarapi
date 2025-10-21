"""Authentication retry helpers for HomGar API interactions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random

from .logutil import get_logger

_LOGGER = get_logger(__file__)


@dataclass(slots=True)
class AuthRetryPolicy:
    """Configuration for login retry behaviour."""

    max_retries: int = 3
    retry_timeout: float = 300.0
    min_backoff: float = 1.0
    max_backoff: float = 60.0


class AuthRetryManager:
    """Stateful helper that applies retry/backoff policy for authentication."""

    def __init__(
        self,
        *,
        policy: AuthRetryPolicy | None = None,
        auth_error_predicate: Callable[[str], bool] | None = None,
        connection_error_predicate: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialise the retry manager with optional predicates and policy."""
        self.policy = policy or AuthRetryPolicy()
        self._retry_count = 0
        self._last_attempt_ts: float = 0.0
        self._auth_error_predicate = auth_error_predicate or (
            lambda err: any(
                indicator in err
                for indicator in ("401", "403", "unauthorized", "forbidden", "invalid credentials")
            )
        )
        self._connection_error_predicate = connection_error_predicate or (
            lambda err: any(
                indicator in err for indicator in ("timeout", "connection", "network", "unreachable")
            )
        )

    @property
    def retry_count(self) -> int:
        """Return the number of consecutive failed attempts."""
        return self._retry_count

    @property
    def last_attempt(self) -> float:
        """Return timestamp of the last login attempt."""
        return self._last_attempt_ts

    def execute(
        self,
        *,
        attempt_ts: float,
        func: Callable[[], None],
        wrap_exception: Callable[[str, float | None], Exception],
    ) -> None:
        """Execute a login attempt honouring policy."""
        self._ensure_not_rate_limited(attempt_ts, wrap_exception)

        try:
            func()
        except Exception as err:
            self._retry_count += 1
            self._last_attempt_ts = attempt_ts
            error_str = str(err).lower()
            if self._auth_error_predicate(error_str):
                raise wrap_exception("invalid_auth", None) from err
            if self._connection_error_predicate(error_str):
                raise wrap_exception("connection_timeout", None) from err
            raise wrap_exception("login_failed", None) from err

        self._retry_count = 0
        self._last_attempt_ts = attempt_ts

    def _ensure_not_rate_limited(
        self,
        attempt_ts: float,
        wrap_exception: Callable[[str, float | None], Exception],
    ) -> None:
        """Ensure we are allowed to attempt another login."""
        if self._retry_count < self.policy.max_retries:
            return
        elapsed = attempt_ts - self._last_attempt_ts
        if elapsed < self.policy.retry_timeout:
            backoff = self._calculate_backoff_delay(self._retry_count)
            raise wrap_exception("rate_limited", backoff)
        self._retry_count = 0

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Return exponential backoff delay with jitter."""
        base_delay = float(min(self.policy.max_backoff, 2**attempt))
        jitter = random.uniform(0.1, 0.5)
        return max(float(self.policy.min_backoff), base_delay * jitter)
