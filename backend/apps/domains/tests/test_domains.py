"""Domains, certificates and approved TLS endpoints (Task 017, docs/06, docs/14, docs/15 A11/A12).

TLS checks run against a throw-away TLS server on 127.0.0.1 with self-signed test
certificates generated here; nothing leaves the machine.
"""

import socket
import ssl
import threading
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.domains import certs, checker, services, tasks
from apps.domains.models import Certificate, CertificateDeployment, DomainRegistration, TlsEndpoint
from apps.imports.tests.test_imports import commit, csv_bytes, preview, upload

pytestmark = pytest.mark.django_db
TODAY = date(2026, 11, 4)


def make_cert(cn="intranet.example.test", sans=("intranet.example.test",), days=200, key=None):
    key = key or ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    start = datetime.now(UTC) - timedelta(days=1)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=days))
    )
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False
        )
    cert = builder.sign(key, hashes.SHA256())
    return cert, key


def pem(cert) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class TlsServer:
    """Accepts TLS handshakes on 127.0.0.1 and presents the current certificate."""

    def __init__(self, tmp_path, cert, key):
        self.tmp_path = tmp_path
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.2)
        self.stop = False
        self.use(cert, key)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def use(self, cert, key):
        cert_file, key_file = self.tmp_path / "c.pem", self.tmp_path / "k.pem"
        cert_file.write_text(pem(cert))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        self.context = context

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            try:
                with self.context.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (ssl.SSLError, OSError):
                pass

    def close(self):
        self.stop = True
        self.thread.join(timeout=2)
        self.sock.close()


@pytest.fixture
def loopback(settings):
    settings.ITAM_TLS_ALLOW_LOOPBACK = True
    settings.ITAM_TLS_CHECK_TIMEOUT_SECONDS = 3


@pytest.fixture
def server(tmp_path, loopback):
    cert, key = make_cert()
    srv = TlsServer(tmp_path, cert, key)
    srv.cert = cert
    yield srv
    srv.close()


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


def endpoint(client, **body):
    response = client.post("/api/v1/tls-endpoints/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def check(client, endpoint_id):
    return client.post(f"/api/v1/tls-endpoints/{endpoint_id}/check/")


# --- Names and parsing ------------------------------------------------------------------------


def test_names_are_normalised_and_urls_refused():
    assert certs.normalize_fqdn(" Example.ORG. ") == "example.org"
    assert certs.normalize_fqdn("bücher.example") == "xn--bcher-kva.example"
    for bad in ("https://example.org", "example.org:443", "example.org/x", "localhost", "1.2.3"):
        with pytest.raises(certs.InvalidName):
            certs.normalize_fqdn(bad)
    assert certs.normalize_host("[::1]") == "::1"
    assert certs.hostname_matches("a.example.test", ["*.example.test"])
    assert not certs.hostname_matches("a.b.example.test", ["*.example.test"])
    assert certs.hostname_matches("x.test", [], "x.test")  # CN only without SANs


def test_expiry_thresholds_and_last_day(settings):
    settings.ITAM_CERT_WARNING_DAYS = [90, 60, 30, 14, 7]
    assert certs.expiry(None, TODAY).status == "unknown"
    assert certs.expiry(TODAY, TODAY).status == "expiring"  # last day still valid
    assert certs.expiry(TODAY - timedelta(days=1), TODAY).status == "expired"
    e = certs.expiry(TODAY + timedelta(days=29), TODAY)
    assert (e.status, e.days_remaining, e.threshold) == ("expiring", 29, 30)
    assert certs.expiry(TODAY + timedelta(days=91), TODAY).status == "ok"
    late = datetime(2026, 11, 4, 23, 30, tzinfo=UTC)
    assert certs.expiry(late, TODAY).days_remaining == 0


# --- Domains (A12) ----------------------------------------------------------------------------


def test_domain_expiry_unknown_until_recorded_with_evidence(admin, admin_user):
    created = admin.post("/api/v1/domains/", {"fqdn": "Example.ORG", "owner": "Web team"})
    assert created.status_code == 201
    d = created.json()
    assert d["fqdn"] == "example.org" and d["expiry"]["status"] == "unknown"
    assert admin.post("/api/v1/domains/", {"fqdn": "example.org"}).status_code == 422
    url = f"/api/v1/domains/{d['id']}/"
    no_evidence = admin.patch(url, {"expires_on": "2027-03-31"}, format="json", HTTP_IF_MATCH='"1"')
    assert no_evidence.status_code == 422
    assert "expiry_evidence" in no_evidence.json()["error"]["field_errors"]
    ok = admin.patch(
        url,
        {"expires_on": "2027-03-31", "expiry_evidence": "Registrar portal"},
        format="json",
        HTTP_IF_MATCH='"1"',
    ).json()
    assert ok["expiry_verified_by"] == admin_user.username and ok["expiry"]["status"] == "ok"
    cleared = admin.patch(url, {"expires_on": None}, format="json", HTTP_IF_MATCH='"2"').json()
    assert cleared["expiry"]["status"] == "unknown" and cleared["expiry_verified_by"] is None
    retired = admin.post(
        f"{url}retire/", {"reason": "Domain sold"}, format="json", HTTP_IF_MATCH='"3"'
    )
    assert retired.status_code == 200
    assert admin.get("/api/v1/domains/").json()["items"] == []
    assert DomainRegistration.objects.count() == 1
    assert AuditEvent.objects.filter(action__startswith="domains.domain.").count() == 4


def test_domain_expiry_never_comes_from_a_certificate(admin, server):
    """A12: a TLS certificate for the domain does not set the registration expiry."""
    d = admin.post("/api/v1/domains/", {"fqdn": "example.test"}).json()
    e = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    assert check(admin, e["id"]).json()["last_status"] == "ok"
    assert admin.get(f"/api/v1/domains/{d['id']}/").json()["expiry"]["status"] == "unknown"


# --- Certificates -----------------------------------------------------------------------------


def test_upload_public_certificates_and_refuse_private_keys(admin):
    cert, key = make_cert(cn="vpn.example.test", sans=("vpn.example.test",), days=20)
    response = admin.post("/api/v1/certificates/", {"pem": pem(cert)}, format="json")
    assert response.status_code == 201
    row = response.json()[0]
    assert row["common_name"] == "vpn.example.test"
    assert row["expiry"]["status"] == "expiring" and row["expiry"]["threshold"] == 30
    assert row["self_signed"] is True and row["source"] == "uploaded"
    again = admin.post("/api/v1/certificates/", {"pem": pem(cert)}, format="json")
    assert again.status_code == 201 and Certificate.objects.count() == 1  # same fingerprint

    secret = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    refused = admin.post("/api/v1/certificates/", {"pem": pem(cert) + secret}, format="json")
    assert refused.status_code == 422 and "private key" in refused.json()["error"]["message"]
    assert "PRIVATE" not in Certificate.objects.get().pem

    listed = admin.get("/api/v1/certificates/", {"expiry": "expiring"}).json()["items"]
    assert [c["common_name"] for c in listed] == ["vpn.example.test"]
    assert admin.get("/api/v1/certificates/", {"expiry": "expired"}).json()["items"] == []
    assert admin.get("/api/v1/certificates/", {"q": row["fingerprint_sha256"][:12]}).json()["items"]


# --- Endpoints and checks ---------------------------------------------------------------------


def test_check_reads_certificate_and_rotation_keeps_history(admin, server, tmp_path):
    e = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    assert e["last_status"] == "never"
    first = check(admin, e["id"]).json()
    assert first["last_status"] == "ok" and first["hostname_matches"] is True
    assert first["tls_version"] in ("TLSv1.2", "TLSv1.3")
    assert first["certificate"]["common_name"] == "intranet.example.test"
    assert check(admin, e["id"]).status_code == 429  # manual checks at most once a minute

    TlsEndpoint.objects.filter(pk=e["id"]).update(last_checked_at=None)
    services.check_endpoint(TlsEndpoint.objects.get(pk=e["id"]))  # same certificate again
    assert CertificateDeployment.objects.count() == 1

    new_cert, new_key = make_cert(cn="other.example.test", sans=("other.example.test",))
    server.use(new_cert, new_key)
    rotated = services.check_endpoint(TlsEndpoint.objects.get(pk=e["id"]))
    assert rotated.current_certificate.common_name == "other.example.test"
    assert rotated.hostname_matches is False
    history = admin.get("/api/v1/certificates/deployments/", {"endpoint": e["id"]}).json()["items"]
    assert [(h["certificate"]["common_name"], h["current"]) for h in history] == [
        ("other.example.test", True),
        ("intranet.example.test", False),
    ]
    old = Certificate.objects.get(common_name="intranet.example.test")
    assert admin.get(f"/api/v1/certificates/{old.pk}/").json()["endpoints"] == 0


def test_one_certificate_on_two_endpoints(admin, server):
    """A11: one certificate, two deployment records, expiry reported once."""
    a = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    b = endpoint(admin, host="127.0.0.1", port=server.port, sni="www.intranet.example.test")
    check(admin, a["id"])
    check(admin, b["id"])
    assert Certificate.objects.count() == 1
    cert = admin.get("/api/v1/certificates/").json()["items"][0]
    assert cert["endpoints"] == 2
    detail = admin.get(f"/api/v1/certificates/{cert['id']}/").json()
    assert len(detail["deployments"]) == 2 and "PRIVATE" not in detail["pem"]


def test_failures_are_recorded_and_keep_last_certificate(admin, server, settings):
    e = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    check(admin, e["id"])
    server.close()
    settings.ITAM_TLS_CHECK_TIMEOUT_SECONDS = 1
    failed = services.check_endpoint(TlsEndpoint.objects.get(pk=e["id"]))
    assert failed.last_status == "failed" and failed.last_error
    assert failed.current_certificate is not None  # the last known certificate stays


def test_ssrf_guards(admin, settings):
    settings.ITAM_TLS_ALLOW_LOOPBACK = False
    for host in ("169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1"):
        response = admin.post("/api/v1/tls-endpoints/", {"host": host}, format="json")
        assert response.status_code == 422, host
    assert (
        admin.post(
            "/api/v1/tls-endpoints/", {"host": "https://intranet.example.test/"}, format="json"
        ).status_code
        == 422
    )
    e = endpoint(admin, host="metadata.example.test")
    assert e["sni"] == "metadata.example.test"
    # DNS answers are checked at connect time (an approved name that resolves to metadata).
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]
    with (
        mock.patch("socket.getaddrinfo", return_value=answers),
        mock.patch("socket.create_connection") as connect,
    ):
        result = check(admin, e["id"]).json()
    connect.assert_not_called()
    assert result["last_status"] == "blocked" and "metadata" in result["last_error"]
    loop = endpoint(admin, host="loop.example.test")
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    with mock.patch("socket.getaddrinfo", return_value=answers):
        assert check(admin, loop["id"]).json()["last_status"] == "blocked"
    assert checker.refused("10.20.30.40") is None  # internal services are the point


def test_scheduled_checks_only_due_enabled_endpoints(admin, server, settings):
    due = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    endpoint(admin, host="127.0.0.1", port=server.port, sni="off.example.test", enabled=False)
    assert tasks.check_endpoints() == {"ok": 1, "failed": 0, "blocked": 0}
    assert tasks.check_endpoints() == {"ok": 0, "failed": 0, "blocked": 0}  # not due yet
    TlsEndpoint.objects.filter(pk=due["id"]).update(
        last_checked_at=datetime.now(UTC) - timedelta(hours=25)
    )
    assert tasks.check_endpoints()["ok"] == 1


def test_endpoint_asset_link_respects_sites(
    admin, client_for, make_user, hq, branch, switch, make_asset
):
    hq_asset = make_asset("web-hq-01", site=hq, category=switch)
    branch_asset = make_asset("web-br-01", site=branch, category=switch)
    engineer = client_for(grant(make_user("hq.eng", roles=["infrastructure_engineer"]), hq))
    assert (
        engineer.post(
            "/api/v1/tls-endpoints/",
            {"host": "br.example.test", "asset": str(branch_asset.pk)},
            format="json",
        ).status_code
        == 404
    )
    mine = endpoint(engineer, host="hq.example.test", asset=str(hq_asset.pk))
    assert mine["asset"]["name"] == "web-hq-01"
    theirs = endpoint(admin, host="br.example.test", asset=str(branch_asset.pk))
    seen = {e["host"]: e for e in engineer.get("/api/v1/tls-endpoints/").json()["items"]}
    assert seen["br.example.test"]["asset"] is None and seen["br.example.test"]["asset_hidden"]
    assert engineer.get(f"/api/v1/assets/{hq_asset.pk}/certificates/").json()[0]["id"] == mine["id"]
    assert engineer.get(f"/api/v1/assets/{branch_asset.pk}/certificates/").status_code == 404
    assert theirs["asset"]["name"] == "web-br-01"


def test_permissions(client_for, make_user, admin):
    reader = client_for(make_user("reader", roles=["read_only"]))
    assert reader.get("/api/v1/domains/").status_code == 200
    assert reader.get("/api/v1/certificates/").status_code == 200
    assert reader.post("/api/v1/domains/", {"fqdn": "example.org"}).status_code == 403
    assert reader.post("/api/v1/tls-endpoints/", {"host": "a.example.test"}).status_code == 403
    nobody = client_for(make_user("nobody", roles=[]))
    assert nobody.get("/api/v1/tls-endpoints/").status_code == 403
    e = endpoint(admin, host="a.example.test")
    assert reader.post(f"/api/v1/tls-endpoints/{e['id']}/check/").status_code == 403


def test_retire_endpoint_closes_deployments(admin, server):
    e = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    check(admin, e["id"])
    retired = admin.post(
        f"/api/v1/tls-endpoints/{e['id']}/retire/",
        {"reason": "Service decommissioned"},
        format="json",
        HTTP_IF_MATCH='"1"',
    ).json()
    assert retired["retired_at"] and retired["enabled"] is False
    assert CertificateDeployment.objects.get().replaced_at is not None
    assert check(admin, e["id"]).status_code == 409
    again = endpoint(admin, host="127.0.0.1", port=server.port, sni="intranet.example.test")
    assert again["id"] != e["id"]  # the same target can be approved again


# --- Imports ----------------------------------------------------------------------------------


def test_domain_and_endpoint_imports(admin, hq, switch, make_asset):
    make_asset("web-hq-01", site=hq, category=switch, asset_tag="IT-0100")
    domains = csv_bytes(
        [
            ["fqdn", "owner", "registrar", "expires_on", "expiry_evidence"],
            ["Example.org", "Web team", "Example Registrar", "2027-03-31", "Registrar portal"],
            ["example.net", "", "", "", ""],
            ["example.org", "", "", "", ""],  # duplicate
            ["bad domain", "", "", "", ""],
            ["example.com", "", "", "2027-01-01", ""],  # date without evidence
        ]
    )
    job = preview(admin, upload(admin, "domain", domains, "d.csv").json())
    totals = job["totals"]
    assert (totals["create"], totals["conflict"], totals["error"]) == (2, 1, 2)
    job = commit(admin, job, key="dom-1").json()
    org = DomainRegistration.objects.get(fqdn="example.org")
    assert org.expires_on == date(2027, 3, 31) and org.expiry_verified_by is not None
    assert DomainRegistration.objects.get(fqdn="example.net").expires_on is None

    endpoints = csv_bytes(
        [
            ["host", "port", "asset_tag", "service", "enabled"],
            ["intranet.example.org", "", "IT-0100", "Intranet", "yes"],
            ["169.254.169.254", "443", "", "", ""],
            ["mail.example.org", "70000", "", "", ""],
            ["vpn.example.org", "8443", "IT-9999", "", ""],
        ]
    )
    job2 = preview(admin, upload(admin, "tls_endpoint", endpoints, "e.csv").json())
    assert (job2["totals"]["create"], job2["totals"]["error"]) == (1, 3)
    commit(admin, job2, key="tls-1")
    e = TlsEndpoint.objects.get()
    assert (e.sni, e.port, e.asset.name, e.service) == (
        "intranet.example.org",
        443,
        "web-hq-01",
        "Intranet",
    )

    rolled = admin.post(
        f"/api/v1/imports/{job['id']}/rollback/",
        {"reason": "Wrong file"},
        format="json",
        HTTP_IF_MATCH=f'"{job["version"]}"',
    ).json()
    assert rolled["totals"]["rollback"]["rolled_back"] == 2
    assert DomainRegistration.objects.filter(retired_at__isnull=True).count() == 0
