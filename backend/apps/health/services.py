"""Dependency health checks used by the readiness endpoint.

The endpoint is unauthenticated, so failure details are logged server-side
and only a generic description is returned (no hostnames or driver errors).
"""

import logging
from dataclasses import dataclass

from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)

UNREACHABLE = "Unreachable. See API logs for details."


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    healthy: bool
    detail: str = ""


def check_database() -> DependencyStatus:
    try:
        connections["default"].cursor().execute("SELECT 1")
    except OperationalError:
        logger.exception("Readiness: database check failed")
        return DependencyStatus(name="database", healthy=False, detail=UNREACHABLE)
    return DependencyStatus(name="database", healthy=True)


def check_redis() -> DependencyStatus:
    from django.conf import settings
    from redis import Redis
    from redis.exceptions import RedisError

    try:
        client = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        client.ping()
    except (RedisError, OSError):
        logger.exception("Readiness: redis check failed")
        return DependencyStatus(name="redis", healthy=False, detail=UNREACHABLE)
    return DependencyStatus(name="redis", healthy=True)


def collect_dependency_statuses() -> list[DependencyStatus]:
    return [check_database(), check_redis()]
