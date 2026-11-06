"""Pinned DNS and TLS regression fixtures; no external service is contacted."""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from apps.integrations.adapters.base import Unavailable, UnsafeTarget, check_host_addresses
from apps.integrations.adapters.entra import ClientSecretCredential, TokenProvider
from apps.integrations.adapters.librenms.client import LibreNMSClient
from apps.integrations.adapters.transport import PinnedTransport

ORIGIN = "https://inventory.example.invalid:8443"


def answers(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (ip, 8443),
        )
        for ip in addresses
    ]


def mock_wire(monkeypatch, handler):
    options = []

    def transport(**kwargs):
        options.append(kwargs)
        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    return options


def test_each_request_pins_fresh_dns_and_preserves_host_sni_and_query(monkeypatch):
    records = iter([answers("10.2.3.4"), answers("10.2.3.5"), answers("127.0.0.1")])
    resolutions, sent = [], []

    def resolve(host, port, **kwargs):
        resolutions.append((host, port))
        return next(records)

    def wire(request):
        sent.append(request)
        return httpx.Response(200, json={})

    mock_wire(monkeypatch, wire)
    with LibreNMSClient(ORIGIN, "fixture-token", resolver=resolve) as client:
        assert client.get("/devices", {"page": "2"}) == {}
        with pytest.raises(UnsafeTarget):
            client.get_continuation(f"{ORIGIN}/api/v0/devices?page=3")
    assert resolutions == [("inventory.example.invalid", 8443)] * 3
    assert len(sent) == 1
    request = sent[0]
    assert request.url.host == "10.2.3.5" and request.url.params["page"] == "2"
    assert request.headers["host"] == "inventory.example.invalid:8443"
    assert request.extensions["sni_hostname"] == "inventory.example.invalid"
    assert request.headers["authorization"] == "Bearer fixture-token"
    assert request.method == "GET" and request.url.path == "/api/v0/devices"


@pytest.mark.parametrize(
    "unsafe",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
        "::ffff:127.0.0.1",
        "0.0.0.0",
        "224.0.0.1",
    ],
)
def test_mixed_dns_answers_rejected_before_transport_creation(monkeypatch, unsafe):
    options = mock_wire(monkeypatch, lambda request: pytest.fail("No request may be sent"))
    with pytest.raises(UnsafeTarget):
        PinnedTransport(ORIGIN, resolver=lambda *a, **kw: answers("10.2.3.4", unsafe))
    assert not options


def test_empty_dns_answers_fail_closed():
    with pytest.raises(Unavailable, match="No addresses"):
        check_host_addresses("empty.invalid", lambda *a, **kw: [])


def test_private_ipv6_preserves_origin_port_and_hostname(monkeypatch):
    sent = []

    def wire(request):
        sent.append(request)
        return httpx.Response(200, json={})

    mock_wire(monkeypatch, wire)
    with LibreNMSClient(
        ORIGIN, "fixture-token", resolver=lambda *a, **kw: answers("fd12:3456::8")
    ) as client:
        assert client.get("/devices") == {}
    assert str(sent[0].url) == "https://[fd12:3456::8]:8443/api/v0/devices"
    assert sent[0].headers["host"] == "inventory.example.invalid:8443"
    assert sent[0].extensions["sni_hostname"] == "inventory.example.invalid"


def test_retry_revalidates_dns_before_sending_again(monkeypatch):
    records = iter([answers("10.2.3.4"), answers("10.2.3.4"), answers("169.254.169.254")])
    sent = []

    def wire(request):
        sent.append(request)
        return httpx.Response(503)

    mock_wire(monkeypatch, wire)
    with LibreNMSClient(
        ORIGIN,
        "fixture-token",
        resolver=lambda *a, **kw: next(records),
        sleep=lambda s: None,
        max_retries=1,
    ) as client:
        with pytest.raises(UnsafeTarget):
            client.get("/devices")
    assert len(sent) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://inventory.example.invalid:8443/",
        "https://other.invalid/",
        "https://inventory.example.invalid:443/",
        "https://user@inventory.example.invalid:8443/",
    ],
)
def test_origin_change_never_reaches_wire(monkeypatch, url):
    mock_wire(monkeypatch, lambda request: pytest.fail("No request may be sent"))
    transport = PinnedTransport(ORIGIN, resolver=lambda *a, **kw: answers("10.2.3.4"))
    with pytest.raises(UnsafeTarget):
        transport.handle_request(httpx.Request("GET", url))
    transport.close()


def test_connection_failover_uses_only_validated_addresses_without_replaying_read_errors(
    monkeypatch,
):
    sent = []

    def wire(request):
        sent.append(request.url.host)
        if len(sent) == 1:
            raise httpx.ConnectError("fixture connection refused")
        raise httpx.ReadTimeout("fixture response timeout")

    mock_wire(monkeypatch, wire)
    transport = PinnedTransport(
        ORIGIN, resolver=lambda *a, **kw: answers("10.2.3.4", "10.2.3.5", "10.2.3.6")
    )
    with pytest.raises(httpx.ReadTimeout):
        transport.handle_request(httpx.Request("POST", f"{ORIGIN}/token", content=b"fixture"))
    assert sent == ["10.2.3.4", "10.2.3.5"]
    transport.close()


def test_inventory_and_oauth_ignore_proxy_and_ca_environment(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("SSL_CERT_FILE", "/not/a/ca.pem")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("10.2.3.4"))
    sent = []

    def wire(request):
        sent.append(request)
        return httpx.Response(
            200, json={"access_token": "fixture", "expires_in": 3600, "token_type": "Bearer"}
        )

    options = mock_wire(monkeypatch, wire)
    with LibreNMSClient(ORIGIN, "fixture-token", verify=False) as client:
        client.get("/devices")
    tokens = TokenProvider(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        ClientSecretCredential("fixture-secret"),
    )
    try:
        assert tokens.token() == "fixture"
    finally:
        tokens.close()
    assert len(sent) == 2 and sent[1].method == "POST"
    assert sent[1].headers["host"] == "login.microsoftonline.com"
    assert sent[1].extensions["sni_hostname"] == "login.microsoftonline.com"
    assert all(item["trust_env"] is False and item["verify"] is True for item in options)


@pytest.fixture
def https_fixture(tmp_path):
    """Temporary test-only trust anchor and loopback HTTPS server with a DNS SAN."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "inventory.example.invalid")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("inventory.example.invalid")]), False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .sign(key, hashes.SHA256())
    )
    ca = tmp_path / "fixture-ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private = tmp_path / "fixture-key.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 2
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(ca, private)
    context.set_servername_callback(lambda sock, hostname, ctx: seen.append(hostname))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, str(ca), seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "host,trusted,success",
    [
        ("inventory.example.invalid", True, True),
        ("wrong.example.invalid", True, False),
        ("inventory.example.invalid", False, False),
    ],
)
def test_real_tls_preserves_sni_and_rejects_wrong_host_or_untrusted_cert(
    monkeypatch, https_fixture, host, trusted, success
):
    port, ca, seen = https_fixture
    connect = socket.create_connection
    destinations = []

    def loopback_wire(address, *args, **kwargs):
        # Only the test socket is contacted. Production still receives the validated IP.
        assert address == ("10.2.3.4", port)
        destinations.append(address)
        return connect(("127.0.0.1", port), *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_wire)
    transport = PinnedTransport(
        f"https://{host}:{port}",
        verify=ca if trusted else False,
        resolver=lambda *a, **kw: answers("10.2.3.4"),
    )
    with httpx.Client(transport=transport, trust_env=False, timeout=3) as client:
        if success:
            assert client.get(f"https://{host}:{port}/api/v0/devices").status_code == 200
            assert seen == [host, f"{host}:{port}"]
        else:
            with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                client.get(f"https://{host}:{port}/api/v0/devices")
    assert destinations == [("10.2.3.4", port)]
