from __future__ import annotations

import time


class BaseApiClient:
    """Shared rate-limiting and retry infrastructure for API clients.

    Subclasses call :meth:`_rate_limit` before each HTTP request and
    :meth:`_mark_request` after a successful round-trip.  Retry loops can
    use :meth:`_retry_delay` for exponential backoff.
    """

    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        max_retries: int = 3,
        retry_sleep: float = 2.0,
        timeout: int = 20,
    ) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.timeout = timeout
        self._last_request_at: float = 0.0

    def _rate_limit(self) -> None:
        """Sleep until *min_interval* has elapsed since the last request."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _mark_request(self) -> None:
        """Record the current monotonic time as the last-request timestamp."""
        self._last_request_at = time.monotonic()

    def _retry_delay(self, attempt: int) -> float:
        """Return the backoff sleep duration for *attempt* (0-based).

        Backoff formula: ``retry_sleep * (1.5 ** attempt)``.
        """
        return self.retry_sleep * (1.5**attempt)
