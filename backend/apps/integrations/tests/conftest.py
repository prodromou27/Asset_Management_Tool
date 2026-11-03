"""LibreNMS test harness: sanitized fixture responses served via httpx.MockTransport.
Nothing here opens a socket."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from apps.integrations import sync
from apps.integrations.models import DiscoverySource, IntegrationInstance

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "librenms" / "api" / "responses.json"
TOKEN = "fixture-token-0123456789abcdef"  # noqa: S105 - fake, test-only
BASE_URL = "https://librenms.corp.example"


def load_responses() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


class FakeLibreNMS:
    """Serves fixture bodies by path. `overrides[path]` may be a (status, body[, headers])
    tuple, an exception instance, or a list of those consumed in order."""

    def __init__(self):
        self.responses = load_responses()
        self.overrides: dict = {}
        self.requests: list[httpx.Request] = []

    def device(self, device_id: int) -> dict:
        return next(d for d in self.responses["/devices"]["devices"] if d["device_id"] == device_id)

    def remove_device(self, device_id: int) -> None:
        devices = self.responses["/devices"]["devices"]
        devices[:] = [d for d in devices if d["device_id"] != device_id]

    def paths(self) -> list[str]:
        return [r.url.path.removeprefix("/api/v0") for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", f"connector sent {request.method}"
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v0")
        override = self.overrides.get(path)
        if isinstance(override, list):
            override = override.pop(0) if len(override) > 1 else override[0]
        if isinstance(override, Exception):
            raise override
        if override is not None:
            status, body, *rest = override
            return httpx.Response(status, json=body, headers=rest[0] if rest else None)
        if path not in self.responses:
            return httpx.Response(404, text="<html>Not Found</html>")
        return httpx.Response(200, json=copy.deepcopy(self.responses[path]))


@pytest.fixture
def fake(monkeypatch):
    server = FakeLibreNMS()
    sleeps: list[float] = []
    server.sleeps = sleeps
    monkeypatch.setattr(
        sync, "TRANSPORT_FACTORY", lambda instance: httpx.MockTransport(server.handler)
    )
    monkeypatch.setattr(sync, "SLEEP", sleeps.append)
    return server


@pytest.fixture
def live(settings, monkeypatch):
    """Deployment-level permission plus a fake token in an approved env reference."""
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = True
    monkeypatch.setenv("ITAM_INTEGRATION_LNMS_TOKEN", TOKEN)


def make_librenms(site, **extra):
    values = {
        "name": "LibreNMS HQ",
        "source": DiscoverySource.objects.get(code="librenms"),
        "default_site": site,
        "base_url": BASE_URL,
        "credential_ref": "env:ITAM_INTEGRATION_LNMS_TOKEN",
        "live_access_approved": True,
        "max_retries": 2,
        "source_timezone": "UTC",
    }
    values.update(extra)
    return IntegrationInstance.objects.create(**values)


@pytest.fixture
def lnms(hq, live, fake):
    return make_librenms(hq)


def run_sync(instance, mode="full"):
    run = sync.queue_sync(instance, mode=mode, triggered_by="test")
    return sync.execute(run.pk)
