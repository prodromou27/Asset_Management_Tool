import pytest
from django.db import connection

from tests.conftest import SQLITE_FALLBACK


@pytest.mark.django_db
def test_suite_runs_on_postgresql_unless_sqlite_explicitly_opted_in():
    if SQLITE_FALLBACK:
        assert connection.vendor == "sqlite"
    else:
        assert connection.vendor == "postgresql"
