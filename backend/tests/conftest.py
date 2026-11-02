import os

import pytest

SQLITE_FALLBACK = os.environ.get("ITAM_TEST_DB_SQLITE") == "1"

requires_postgres = pytest.mark.skipif(
    SQLITE_FALLBACK, reason="integration test requires PostgreSQL and Redis"
)
