"""Unmocked readiness checks against the real PostgreSQL and Redis services."""

import pytest
from django.db import connection
from rest_framework.test import APIClient

from tests.conftest import requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


@pytest.mark.django_db
def test_readiness_reports_real_postgres_and_redis_up():
    response = APIClient().get("/api/v1/health/ready/")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"]["status"] == "up"
    assert body["dependencies"]["redis"]["status"] == "up"
    assert connection.vendor == "postgresql"


@pytest.mark.django_db
def test_readiness_reports_redis_down_for_unreachable_broker(settings):
    settings.CELERY_BROKER_URL = "redis://127.0.0.1:1/0"

    response = APIClient().get("/api/v1/health/ready/")

    assert response.status_code == 503
    assert response.json()["dependencies"]["redis"]["status"] == "down"
