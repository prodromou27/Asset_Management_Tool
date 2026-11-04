"""Scheduled certificate reads of approved TLS endpoints."""

import logging

from celery import shared_task

from . import services

logger = logging.getLogger(__name__)
BATCH = 200


@shared_task(name="domains.check_endpoints", ignore_result=True)
def check_endpoints() -> dict:
    """Check enabled endpoints whose last check is older than the interval (default 24 h).
    At most BATCH per run; the rest follow on the next run."""
    counts = {"ok": 0, "failed": 0, "blocked": 0}
    for endpoint in services.due_endpoints().order_by("last_checked_at")[:BATCH]:
        endpoint = services.check_endpoint(endpoint)
        key = endpoint.last_status if endpoint.last_status in counts else "failed"
        counts[key] += 1
    if any(counts.values()):
        logger.info("TLS endpoint checks: %s", counts)
    return counts
