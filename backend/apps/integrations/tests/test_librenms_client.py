"""Read-only HTTP client, target safety checks, secret references and mapping helpers."""

import socket

import httpx
import pytest

from apps.integrations import secrets
from apps.integrations.adapters.base import AuthError, NotSupported, SourceError, UnsafeTarget
from apps.integrations.adapters.librenms.client import LibreNMSClient
from apps.integrations.adapters.librenms.mapping import device_to_record, parse_source_time

from .conftest import BASE_URL, TOKEN


def client_for(handler, **extra):
    return LibreNMSClient(
        BASE_URL, TOKEN, transport=httpx.MockTransport(handler), sleep=lambda s: None, **extra
    )


def resolver_for(address):
    def resolve(host, port, proto=0):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, proto, "", (address, port))]

    return resolve


def test_client_exposes_no_write_methods():
    client = client_for(lambda r: httpx.Response(200, json={}))
    for verb in ("post", "put", "patch", "delete", "request"):
        assert not hasattr(client, verb)


@pytest.mark.parametrize(
    "url",
    [
        "http://librenms.corp.example",
        "https://user:pw@librenms.corp.example",
        "https://h.example/?a=1",
        "ftp://x",
    ],
)
def test_only_plain_https_base_urls(url):
    with pytest.raises(UnsafeTarget):
        LibreNMSClient(url, TOKEN, transport=httpx.MockTransport(lambda r: None))


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "::1", "0.0.0.0", "224.0.0.1"])
def test_unsafe_resolved_addresses_are_refused(address):
    with pytest.raises(UnsafeTarget):
        LibreNMSClient(BASE_URL, TOKEN, resolver=resolver_for(address))


def test_private_addresses_are_allowed():
    LibreNMSClient(BASE_URL, TOKEN, resolver=resolver_for("10.20.30.40")).close()


def test_redirects_are_refused_not_followed():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    with pytest.raises(SourceError, match="redirect"):
        client_for(handler).get("/devices")
    assert len(seen) == 1


def test_empty_list_messages_are_empty_results_and_missing_routes_are_not_supported():
    def handler(request):
        if request.url.path.endswith("/ip"):
            return httpx.Response(404, json={"status": "error", "message": "No IP addresses found"})
        return httpx.Response(404, text="<html>missing</html>")

    client = client_for(handler)
    assert client.get("/devices/1/ip") == {}
    with pytest.raises(NotSupported):
        client.get("/resources/fdb")


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_never_include_the_token(status):
    client = client_for(lambda r: httpx.Response(status, json={"message": TOKEN}))
    with pytest.raises(AuthError) as exc:
        client.get("/system")
    assert TOKEN not in str(exc.value)
    assert client.requests == 1
    assert TOKEN not in repr(client)


def test_server_errors_are_retried_then_succeed():
    responses = [httpx.Response(503), httpx.Response(200, json={"status": "ok", "devices": []})]
    client = client_for(lambda r: responses.pop(0), max_retries=2)
    assert client.get("/devices") == {"status": "ok", "devices": []}
    assert client.requests == 2


def test_non_json_and_error_envelopes_are_source_errors():
    with pytest.raises(SourceError, match="not JSON"):
        client_for(lambda r: httpx.Response(200, text="<html/>")).get("/devices")
    with pytest.raises(SourceError, match="Insufficient"):
        client_for(
            lambda r: httpx.Response(
                200, json={"status": "error", "message": "Insufficient rights"}
            )
        ).get("/devices")


def test_throttle_spaces_requests():
    waits = []
    client = LibreNMSClient(
        BASE_URL,
        TOKEN,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        requests_per_second=2,
        sleep=waits.append,
    )
    for _ in range(3):
        client.get("/system")
    assert len(waits) == 2 and all(0 < w <= 0.5 for w in waits)


# --- Secret references --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "env:DJANGO_SECRET_KEY",
        "env:POSTGRES_PASSWORD",
        "file:../etc/passwd",
        "file:a/b",
        "vault:x",
        "plaintext",
    ],
)
def test_unsafe_secret_references_are_rejected(ref):
    with pytest.raises(secrets.SecretError):
        secrets.validate_ref(ref)


def test_secret_references_resolve_from_env_and_files(tmp_path, settings, monkeypatch):
    settings.ITAM_SECRETS_DIR = str(tmp_path)
    (tmp_path / "librenms_token").write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("ITAM_INTEGRATION_X", "env-token")

    assert secrets.resolve("env:ITAM_INTEGRATION_X") == "env-token"
    assert secrets.resolve("file:librenms_token") == "file-token"
    assert secrets.status("file:librenms_token") == "configured"
    assert secrets.status("file:absent") == "missing"
    assert secrets.status("env:NOPE") == "invalid"
    assert secrets.status("") == "not_set"
    with pytest.raises(secrets.SecretError) as exc:
        secrets.resolve("env:ITAM_INTEGRATION_EMPTY")
    assert "env-token" not in str(exc.value)


# --- Mapping helpers ---------------------------------------------------------------------------


def test_parse_source_time_handles_zones_and_empty_values():
    assert parse_source_time("2026-07-01 12:00:00", "Europe/Nicosia") == "2026-07-01T09:00:00+00:00"
    assert parse_source_time("2026-07-01 12:00:00", "Not/AZone") == "2026-07-01T12:00:00+00:00"
    assert parse_source_time("0000-00-00 00:00:00", "UTC") is None
    assert parse_source_time(None, "UTC") is None


def test_device_without_poll_time_uses_fetch_time_and_strips_credentials():
    record, warnings = device_to_record(
        {
            "device_id": 5,
            "hostname": "x.example",
            "community": "c",
            "cryptopass": "p",
            "os": "junos",
        },
        ips=[],
        ports=[],
        inventory=[],
        tz_name="UTC",
        fetched_at="2026-11-03T00:00:00+00:00",
        enriched_at=None,
    )
    assert record["observed_at"] == "2026-11-03T00:00:00+00:00" and warnings
    assert (
        "community" not in record["raw"]["device"] and "cryptopass" not in record["raw"]["device"]
    )
    assert record["manufacturer"] == "Juniper"


def test_vendor_falls_back_to_enterprise_oid():
    record, _ = device_to_record(
        {
            "device_id": 6,
            "hostname": "y.example",
            "os": "unknownos",
            "sysObjectID": ".1.3.6.1.4.1.2011.2.1",
        },
        ips=[],
        ports=[],
        inventory=[],
        tz_name="UTC",
        fetched_at="2026-11-03T00:00:00+00:00",
        enriched_at=None,
    )
    assert record["manufacturer"] == "Huawei"
