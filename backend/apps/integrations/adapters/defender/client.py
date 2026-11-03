"""Read-only Microsoft Defender for Endpoint API client.

GET only (adapters/http.py), fixed to ``https://api.security.microsoft.com/api``. Tokens
come from Microsoft Entra for the Defender for Endpoint API audience
(``https://api.securitycenter.microsoft.com/.default``), not Microsoft Graph. The only
resource read is ``/api/machines``. Device actions (isolation, scans, quarantine, live
response, offboarding) and Advanced Hunting are never called.

Published API limits: 100 calls per minute and 1,500 calls per hour per tenant. Every
process and run for the same tenant shares one budget kept in the Django cache (Redis in
deployments), counted with a sliding window over the current and previous minute and hour:
- at most 90 calls per minute: the client waits for the next minute;
- at most 1,400 calls per hour: the client stops with ``BudgetExhausted``
  (non-retryable), so the listing is treated as incomplete.
In addition no single client sends more than one request per 0.6 s. If the cache is
unavailable the budget falls back to this process only, with a warning in the log.
"""

import logging
import time
from collections import deque

from django.core.cache import cache

from ..base import SourceError
from ..intune.client import GraphClient

logger = logging.getLogger(__name__)

API_BASE = "https://api.security.microsoft.com"
API_PREFIX = "/api"
REQUIRED_PERMISSION = "Machine.Read.All"
MIN_INTERVAL = 0.6  # 100 calls per minute from one client
MINUTE_BUDGET = 90  # below the published 100 calls per minute
HOURLY_BUDGET = 1400  # below the published 1,500 calls per hour
MAX_MINUTE_WAITS = 3

# Wall clock for the shared windows (tests move it).
now = time.time


class BudgetExhausted(SourceError):
    code = "SOURCE_RATE_BUDGET"


def _window_estimate(key: str, span: int, at: float) -> float:
    """Sliding-window estimate: this window's count plus the previous window's count
    weighted by the part of it that still overlaps the last `span` seconds."""
    index = int(at // span)
    current = cache.get(f"{key}:{span}:{index}", 0)
    previous = cache.get(f"{key}:{span}:{index - 1}", 0)
    elapsed = (at % span) / span
    return current + previous * (1 - elapsed)


def _count(key: str, span: int, at: float) -> None:
    slot = f"{key}:{span}:{int(at // span)}"
    cache.add(slot, 0, timeout=span * 2 + 10)
    try:
        cache.incr(slot)
    except ValueError:  # expired between add and incr
        cache.set(slot, 1, timeout=span * 2 + 10)


class DefenderClient(GraphClient):
    base = API_BASE
    api_prefix = API_PREFIX
    user_agent = "ITAM-Defender-Connector/1 (read-only)"
    source_label = "Microsoft Defender for Endpoint"
    required_permission = f"{REQUIRED_PERMISSION} (WindowsDefenderATP API)"
    license_hint = "and the tenant needs Defender for Endpoint"
    continuation_paths = ("/machines",)

    def __init__(self, tokens, *, clock=time.monotonic, **kwargs):
        super().__init__(tokens, **kwargs)
        self.min_interval = max(self.min_interval, MIN_INTERVAL)
        self._clock = clock
        self._recent: deque[float] = deque()  # fallback when the cache is unavailable
        self._budget_key = f"defender-budget:{str(tokens.tenant_id).lower()}"

    def _exhausted(self) -> BudgetExhausted:
        return BudgetExhausted(
            f"Stopped before exceeding the Defender API hourly limit ({HOURLY_BUDGET} "
            "requests in the last hour for this tenant)."
        )

    def _reserve_shared(self) -> None:
        for _ in range(MAX_MINUTE_WAITS + 1):
            at = now()
            if _window_estimate(self._budget_key, 3600, at) >= HOURLY_BUDGET:
                raise self._exhausted()
            if _window_estimate(self._budget_key, 60, at) < MINUTE_BUDGET:
                _count(self._budget_key, 3600, at)
                _count(self._budget_key, 60, at)
                return
            wait = 60 - (at % 60) + 0.1
            logger.info("Defender per-minute budget reached; waiting %.1fs", wait)
            self._sleep(wait)
        raise BudgetExhausted("The Defender API per-minute budget stayed exhausted.")

    def _reserve_local(self) -> None:
        at = self._clock()
        while self._recent and at - self._recent[0] >= 3600:
            self._recent.popleft()
        if len(self._recent) >= HOURLY_BUDGET:
            raise self._exhausted()
        self._recent.append(at)

    def _throttle(self) -> None:
        try:
            self._reserve_shared()
        except BudgetExhausted:
            raise
        except Exception:  # noqa: BLE001 - cache down: keep a per-process budget
            logger.warning("Shared Defender rate budget unavailable; using a local budget")
            self._reserve_local()
        super()._throttle()
