# Reuse the connector test harness (fake Endpoint Central and Graph servers).
from apps.integrations.tests.conftest import (  # noqa: F401
    ec,
    ec_fake,
    graph,
    intune,
    live,
)
