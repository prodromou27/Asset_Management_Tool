import pytest

from apps.health.services import check_database


@pytest.mark.django_db
def test_check_database_healthy_against_test_database():
    status = check_database()

    assert status.healthy is True
    assert status.name == "database"


def test_redis_failure_detail_is_generic(settings):
    from apps.health.services import UNREACHABLE, check_redis

    settings.CELERY_BROKER_URL = "redis://internal-cache.example.invalid:1/0"

    status = check_redis()

    assert status.healthy is False
    assert status.detail == UNREACHABLE
    assert "example.invalid" not in status.detail
