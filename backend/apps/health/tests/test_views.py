from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.health.services import DependencyStatus


@pytest.fixture
def client():
    return APIClient()


def test_liveness_returns_ok_without_touching_dependencies(client):
    response = client.get("/api/v1/health/live/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_ok_when_dependencies_are_healthy(client):
    healthy = [
        DependencyStatus(name="database", healthy=True),
        DependencyStatus(name="redis", healthy=True),
    ]
    with patch("apps.health.views.services.collect_dependency_statuses", return_value=healthy):
        response = client.get("/api/v1/health/ready/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"]["status"] == "up"
    assert body["dependencies"]["redis"]["status"] == "up"


def test_readiness_returns_503_when_database_is_down(client):
    degraded = [
        DependencyStatus(name="database", healthy=False, detail="connection refused"),
        DependencyStatus(name="redis", healthy=True),
    ]
    with patch("apps.health.views.services.collect_dependency_statuses", return_value=degraded):
        response = client.get("/api/v1/health/ready/")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["status"] == "down"
    assert body["dependencies"]["database"]["detail"] == "connection refused"
