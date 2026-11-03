"""Read-only Microsoft Defender for Endpoint API client.

GET only (adapters/http.py), fixed to ``https://api.security.microsoft.com/api``. Tokens
come from Microsoft Entra for the Defender for Endpoint API audience
(``https://api.securitycenter.microsoft.com/.default``), not Microsoft Graph. The only
resource read is ``/api/machines``. Device actions (isolation, scans, quarantine, live
response, offboarding) and Advanced Hunting are never called.

Published API limits: 100 calls per minute and 1,500 calls per hour. The client never
sends more than one request per 0.6 s whatever the instance setting, and stops with
``BudgetExhausted`` (non-retryable) before the hourly budget is used up.
"""

import time
from collections import deque

from ..base import SourceError
from ..intune.client import GraphClient

API_BASE = "https://api.security.microsoft.com"
API_PREFIX = "/api"
REQUIRED_PERMISSION = "Machine.Read.All"
MIN_INTERVAL = 0.6  # 100 calls per minute
HOURLY_BUDGET = 1400  # below the published 1,500 calls per hour, leaving headroom


class BudgetExhausted(SourceError):
    code = "SOURCE_RATE_BUDGET"


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
        self._recent: deque[float] = deque()

    def _throttle(self) -> None:
        now = self._clock()
        while self._recent and now - self._recent[0] >= 3600:
            self._recent.popleft()
        if len(self._recent) >= HOURLY_BUDGET:
            raise BudgetExhausted(
                f"Stopped before exceeding the Defender API hourly limit ({HOURLY_BUDGET} "
                "requests in the last hour)."
            )
        super()._throttle()
        self._recent.append(self._clock())
