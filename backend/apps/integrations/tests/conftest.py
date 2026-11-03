"""LibreNMS, Endpoint Central and Intune (Graph) test harness: sanitized fixtures served by
httpx.MockTransport. Nothing here opens a socket."""

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


# --- Endpoint Central ---------------------------------------------------------------------

EC_FIXTURE = (
    Path(__file__).resolve().parents[4] / "fixtures" / "endpoint_central" / "api" / "responses.json"
)
EC_BASE_URL = "https://ec.corp.example:8383"
EC_TOKEN = "ec-fixture-key-9f8e7d6c5b4a"  # noqa: S105 - fake, test-only


class FakeEndpointCentral:
    """Serves the fixture for the enabled API generations ("api_1_4" by default).
    Listing pages are sliced from the fixture by the requested page and limit.
    `overrides[path]` works as in FakeLibreNMS; keys may also be "path#page"."""

    def __init__(self):
        data = json.loads(EC_FIXTURE.read_text(encoding="utf-8"))
        self.v14 = data["api_1_4"]
        self.dc = data["dcapi"]
        self.families = {"api_1_4"}
        self.overrides: dict = {}
        self.requests: list[httpx.Request] = []
        self.total_override = None

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def computer(self, resource_id: int) -> dict:
        return next(c for c in self.v14["computers"] if c["resource_id"] == resource_id)

    def details(self, resource_id: int) -> dict:
        return self.v14["details"][str(resource_id)]["message_response"]["compdetailssummary"]

    def remove(self, resource_id: int) -> None:
        self.v14["computers"] = [
            c for c in self.v14["computers"] if c["resource_id"] != resource_id
        ]

    @staticmethod
    def _page(rows, page, limit):
        return rows[(page - 1) * limit : page * limit]

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", f"connector sent {request.method}"
        self.requests.append(request)
        path, params = request.url.path, request.url.params
        page = int(params.get("page", 1))
        for key in (f"{path}#{page}", path):
            override = self.overrides.get(key)
            if isinstance(override, list):
                override = override.pop(0) if len(override) > 1 else override[0]
            if isinstance(override, Exception):
                raise override
            if override is not None:
                status, body, *rest = override
                return httpx.Response(status, json=body, headers=rest[0] if rest else None)
        if path == "/api/1.4/inventory/scancomputers" and "api_1_4" in self.families:
            limit = int(params.get("pagelimit", 25))
            rows = self.v14["computers"]
            total = len(rows) if self.total_override is None else self.total_override
            body = {
                "message_type": "scancomputers",
                "message_version": "1.0",
                "status": "success",
                "message_response": {
                    "scancomputers": copy.deepcopy(self._page(rows, page, limit)),
                    "total": total,
                    "limit": limit,
                    "page": page,
                },
            }
            return httpx.Response(200, json=body)
        if path == "/api/1.4/inventory/compdetailssummary" and "api_1_4" in self.families:
            doc = self.v14["details"].get(params.get("resid", ""))
            if doc is None:
                return httpx.Response(
                    200,
                    json={"status": "error", "error_code": "10004", "error_description": "No data"},
                )
            return httpx.Response(200, json=copy.deepcopy(doc))
        if path == "/api/1.4/desktop/serverproperties" and "api_1_4" in self.families:
            return httpx.Response(200, json=self.v14["server"])
        if path == "/dcapi/inventory/viewData/scanComputers" and "dcapi" in self.families:
            limit = int(params.get("pageLimit", 25))
            rows = self.dc["computers"]
            body = {
                "status": "success",
                "metadata": {"totalRecords": len(rows), "page": page, "pageLimit": limit},
                "data": copy.deepcopy(self._page(rows, page, limit)),
            }
            return httpx.Response(200, json=body)
        if path.startswith("/dcapi/inventory/computers/") and "dcapi" in self.families:
            resource_id, _, part = path.removeprefix("/dcapi/inventory/computers/").partition("/")
            doc = self.dc["details"].get(resource_id, {}).get(part)
            if doc is not None:
                return httpx.Response(200, json=copy.deepcopy(doc))
        return httpx.Response(404, text="<html>Not Found</html>")


@pytest.fixture
def ec_fake(monkeypatch):
    server = FakeEndpointCentral()
    sleeps: list[float] = []
    server.sleeps = sleeps
    monkeypatch.setattr(
        sync, "TRANSPORT_FACTORY", lambda instance: httpx.MockTransport(server.handler)
    )
    monkeypatch.setattr(sync, "SLEEP", sleeps.append)
    return server


def make_endpoint_central(site, **extra):
    values = {
        "name": "Endpoint Central",
        "source": DiscoverySource.objects.get(code="endpoint_central"),
        "default_site": site,
        "base_url": EC_BASE_URL,
        "credential_ref": "env:ITAM_INTEGRATION_EC_TOKEN",
        "auth_scheme": "authorization",
        "live_access_approved": True,
        "max_retries": 1,
        "source_timezone": "UTC",
    }
    values.update(extra)
    return IntegrationInstance.objects.create(**values)


@pytest.fixture
def ec(hq, live, ec_fake, monkeypatch):
    monkeypatch.setenv("ITAM_INTEGRATION_EC_TOKEN", EC_TOKEN)
    return make_endpoint_central(hq)


# --- Microsoft Intune (Graph v1.0) -----------------------------------------------------

INTUNE_FIXTURE = (
    Path(__file__).resolve().parents[4] / "fixtures" / "intune" / "graph" / "responses.json"
)
INTUNE_SECRET = "fixture-client-secret-not-real"  # noqa: S105 - fake, test-only
GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"
COLLECTION = "/v1.0/deviceManagement/managedDevices"
READ_ROLE = "DeviceManagementManagedDevices.Read.All"


def _b64(data: dict | bytes) -> str:
    import base64

    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def fake_jwt(roles: list[str], serial: int) -> str:
    """Unsigned token-shaped string; the connector only reads its roles claim."""
    return f"{_b64({'alg': 'none'})}.{_b64({'roles': roles, 'n': serial})}.sig"


class FakeGraph:
    """Entra token endpoint + Graph managedDevices served from the fixture.

    Pages of `page_size` devices are linked with @odata.nextLink ($skiptoken=<page>).
    `overrides[key]` (key "token" or "page<N>") is a (status, body[, headers]) tuple, an
    exception, or a list of those consumed in order. Graph only ever accepts GET; the
    token endpoint only POST to the fixture tenant's path."""

    def __init__(self):
        data = json.loads(INTUNE_FIXTURE.read_text(encoding="utf-8"))
        self.tenant_id = data["tenant_id"]
        self.client_id = data["client_id"]
        self.devices: list[dict] = data["managedDevices"]
        self.page_size = 4
        self.roles = [READ_ROLE]
        self.overrides: dict = {}
        self.requests: list[httpx.Request] = []
        self.token_forms: list[dict] = []
        self.valid_tokens: set[str] = set()
        self.reject_select = False
        self.next_link_base = f"https://{GRAPH_HOST}{COLLECTION}"
        self.expires_in = 3599

    def device(self, suffix: int) -> dict:
        return next(d for d in self.devices if d["id"].endswith(f"{suffix:012d}"))

    def remove(self, suffix: int) -> None:
        self.devices[:] = [d for d in self.devices if not d["id"].endswith(f"{suffix:012d}")]

    def expire_tokens(self) -> None:
        self.valid_tokens.clear()

    def _override(self, key):
        override = self.overrides.get(key)
        if isinstance(override, list):
            override = override.pop(0) if len(override) > 1 else override[0]
        if isinstance(override, Exception):
            raise override
        if override is not None:
            status, body, *rest = override
            return httpx.Response(status, json=body, headers=rest[0] if rest else None)
        return None

    def handler(self, request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        if request.url.host == LOGIN_HOST:
            assert request.method == "POST", f"token endpoint got {request.method}"
            assert request.url.path == f"/{self.tenant_id}/oauth2/v2.0/token"
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            if (response := self._override("token")) is not None:
                return response
            token = fake_jwt(self.roles, len(self.token_forms))
            self.valid_tokens.add(token)
            return httpx.Response(
                200,
                json={"token_type": "Bearer", "expires_in": self.expires_in, "access_token": token},
            )

        assert request.url.host == GRAPH_HOST, f"request to {request.url.host}"
        assert request.method == "GET", f"connector sent {request.method} to Graph"
        assert request.url.path == COLLECTION, request.url.path
        self.requests.append(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.valid_tokens:
            return httpx.Response(
                401,
                json={
                    "error": {
                        "code": "InvalidAuthenticationToken",
                        "message": "Lifetime validation failed, the token is expired.",
                    }
                },
            )
        params = request.url.params
        page = int(params.get("$skiptoken", 1))
        if (response := self._override(f"page{page}")) is not None:
            return response
        select = params.get("$select")
        if select and self.reject_select and "$top" not in params:
            return httpx.Response(
                400,
                json={"error": {"code": "BadRequest", "message": "Could not find a property."}},
            )
        if "$top" in params:
            rows, more = self.devices[: int(params["$top"])], False
        else:
            start = (page - 1) * self.page_size
            rows = self.devices[start : start + self.page_size]
            more = start + self.page_size < len(self.devices)
        if select:
            keys = set(select.split(","))
            rows = [{k: v for k, v in r.items() if k in keys} for r in rows]
        body = {
            "@odata.context": f"https://{GRAPH_HOST}/v1.0/$metadata#deviceManagement/managedDevices",
            "value": copy.deepcopy(rows),
        }
        if more:
            query = f"$select={select}&" if select else ""
            body["@odata.nextLink"] = f"{self.next_link_base}?{query}$skiptoken={page + 1}"
        return httpx.Response(200, json=body)

    def graph_pages(self) -> list[int]:
        return [int(r.url.params.get("$skiptoken", 1)) for r in self.requests]


@pytest.fixture
def graph(monkeypatch):
    server = FakeGraph()
    sleeps: list[float] = []
    server.sleeps = sleeps
    monkeypatch.setattr(
        sync, "TRANSPORT_FACTORY", lambda instance: httpx.MockTransport(server.handler)
    )
    monkeypatch.setattr(sync, "SLEEP", sleeps.append)
    return server


def make_intune(site, server: FakeGraph, **extra):
    values = {
        "name": "Intune",
        "source": DiscoverySource.objects.get(code="intune"),
        "default_site": site,
        "base_url": "https://graph.microsoft.com",
        "tenant_id": server.tenant_id,
        "client_id": server.client_id,
        "credential_ref": "env:ITAM_INTEGRATION_INTUNE_SECRET",
        "auth_scheme": "client_secret",
        "live_access_approved": True,
        "max_retries": 2,
        "stale_after_hours": 168,
    }
    values.update(extra)
    return IntegrationInstance.objects.create(**values)


@pytest.fixture
def intune(hq, live, graph, monkeypatch):
    monkeypatch.setenv("ITAM_INTEGRATION_INTUNE_SECRET", INTUNE_SECRET)
    return make_intune(hq, graph)
