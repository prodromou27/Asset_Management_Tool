"""Domains, certificates and TLS endpoint checks (Task 017, ASM-56). Every manual change is
audited; domains and endpoints are retired, never deleted."""

from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ApiError

from . import certs, checker
from .models import Certificate, CertificateDeployment, DomainRegistration, TlsEndpoint

DOMAIN_FIELDS = (
    "fqdn",
    "owner",
    "registrar",
    "expires_on",
    "expiry_evidence",
    "auto_renew",
    "note",
)
ENDPOINT_FIELDS = ("host", "port", "sni", "asset", "service", "owner", "enabled", "note")


def today_utc():
    return datetime.now(UTC).date()


def _value(v):
    if hasattr(v, "pk"):
        return str(v.pk)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _snap(obj, fields) -> dict:
    return {f: _value(getattr(obj, f)) for f in fields}


def _record(request, action, obj, before=None, after=None, detail=""):
    audit.record(
        action=f"domains.{action}",
        actor=getattr(request, "user", None),
        request=request,
        object_type=obj._meta.model_name,
        object_id=obj.pk,
        object_label=str(obj),
        before=before,
        after=after,
        detail=detail,
    )


def _invalid(field: str, message: str):
    return ApiError("VALIDATION_ERROR", message, 422, {field: [message]})


# --- Domains ----------------------------------------------------------------------------------


def _clean_domain(data: dict, current: DomainRegistration | None = None) -> dict:
    data = dict(data)
    if "fqdn" in data:
        try:
            data["fqdn"] = certs.normalize_fqdn(data["fqdn"])
        except certs.InvalidName as exc:
            raise _invalid("fqdn", str(exc)) from exc
    expires = data.get("expires_on", current.expires_on if current else None)
    evidence = data.get("expiry_evidence", current.expiry_evidence if current else "")
    if expires and not (evidence or "").strip():
        raise _invalid(
            "expiry_evidence",
            "Say where the expiry date comes from (registrar portal, invoice, WHOIS record).",
        )
    return data


def _verify(domain, request, before_expiry, before_evidence) -> None:
    """The person who records or changes the expiry date vouches for it."""
    if domain.expires_on != before_expiry or domain.expiry_evidence != before_evidence:
        if domain.expires_on:
            domain.expiry_verified_by, domain.expiry_verified_at = request.user, timezone.now()
        else:
            domain.expiry_verified_by, domain.expiry_verified_at = None, None
            domain.expiry_evidence = ""


@transaction.atomic
def create_domain(request, data: dict) -> DomainRegistration:
    data = _clean_domain(data)
    if DomainRegistration.objects.filter(fqdn=data["fqdn"]).exists():
        raise _invalid("fqdn", "This domain is already registered in ITAM.")
    domain = DomainRegistration(**data, created_by=request.user, modified_by=request.user)
    _verify(domain, request, None, "")
    domain.save()
    _record(request, "domain.create", domain, after=_snap(domain, DOMAIN_FIELDS))
    return domain


@transaction.atomic
def update_domain(request, domain: DomainRegistration, data: dict, expected):
    domain = DomainRegistration.objects.select_for_update().get(pk=domain.pk)
    check_version(domain, expected)
    if domain.retired_at:
        raise ApiError("DOMAIN_RETIRED", "Retired domains cannot be changed.", 409)
    data = _clean_domain(data, domain)
    if "fqdn" in data and (
        DomainRegistration.objects.filter(fqdn=data["fqdn"]).exclude(pk=domain.pk).exists()
    ):
        raise _invalid("fqdn", "This domain is already registered in ITAM.")
    before = _snap(domain, DOMAIN_FIELDS)
    before_expiry, before_evidence = domain.expires_on, domain.expiry_evidence
    for name in DOMAIN_FIELDS:
        if name in data:
            setattr(domain, name, data[name])
    _verify(domain, request, before_expiry, before_evidence)
    domain.modified_by = request.user
    domain.version = F("version") + 1
    domain.save()
    domain.refresh_from_db()
    _record(
        request,
        "domain.update",
        domain,
        before=before,
        after=_snap(domain, DOMAIN_FIELDS),
        detail=data.get("reason", ""),
    )
    return domain


@transaction.atomic
def retire_domain(request, domain: DomainRegistration, reason: str, expected):
    domain = DomainRegistration.objects.select_for_update().get(pk=domain.pk)
    check_version(domain, expected)
    if domain.retired_at:
        raise ApiError("DOMAIN_RETIRED", "This domain is already retired.", 409)
    domain.retired_at, domain.retired_reason = timezone.now(), reason[:500]
    domain.modified_by = request.user
    domain.version = F("version") + 1
    domain.save()
    domain.refresh_from_db()
    _record(request, "domain.retire", domain, detail=reason)
    return domain


# --- Certificates -----------------------------------------------------------------------------


def store_certificate(fields: dict, source: str, user=None, now=None) -> tuple[Certificate, bool]:
    now = now or timezone.now()
    defaults = {**fields, "source": source, "first_seen_at": now, "created_by": user}
    cert, created = Certificate.objects.get_or_create(
        fingerprint_sha256=fields["fingerprint_sha256"], defaults=defaults
    )
    return cert, created


def upload_certificates(request, pem: str, note: str = "") -> list[Certificate]:
    try:
        parsed = certs.parse_upload(pem)
    except certs.CertificateError as exc:
        raise _invalid("pem", str(exc)) from exc
    stored = []
    with transaction.atomic():
        for fields in parsed:
            cert, created = store_certificate(
                {**fields, "note": note[:500]}, Certificate.Source.UPLOADED, request.user
            )
            stored.append(cert)
            if created:
                _record(
                    request,
                    "certificate.upload",
                    cert,
                    after={
                        "fingerprint_sha256": cert.fingerprint_sha256,
                        "not_after": cert.not_after.isoformat(),
                    },
                )
    return stored


# --- TLS endpoints ----------------------------------------------------------------------------


def _clean_endpoint(data: dict, current: TlsEndpoint | None = None) -> dict:
    data = dict(data)
    if "host" in data:
        try:
            data["host"] = certs.normalize_host(data["host"])
        except certs.InvalidName as exc:
            raise _invalid("host", str(exc)) from exc
    host = data.get("host", current.host if current else "")
    if "sni" in data and data["sni"]:
        try:
            data["sni"] = certs.normalize_fqdn(data["sni"])
        except certs.InvalidName as exc:
            raise _invalid("sni", str(exc)) from exc
    elif current is None and not data.get("sni") and not certs.is_ip(host):
        data["sni"] = host  # default: present the host name, as browsers do
    if certs.is_ip(host) and (reason := checker.refused(host)):
        raise _invalid("host", f"ITAM does not connect to this address ({reason}).")
    return data


def _duplicate_endpoint(data: dict, exclude=None) -> bool:
    qs = TlsEndpoint.objects.filter(
        host=data["host"], port=data["port"], sni=data.get("sni", ""), retired_at__isnull=True
    )
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.exists()


@transaction.atomic
def create_endpoint(request, data: dict) -> TlsEndpoint:
    data = _clean_endpoint(data)
    data.setdefault("port", 443)
    if _duplicate_endpoint(data):
        raise _invalid("host", "This host, port and SNI is already an approved endpoint.")
    endpoint = TlsEndpoint(**data, created_by=request.user, modified_by=request.user)
    endpoint.save()
    _record(request, "endpoint.create", endpoint, after=_snap(endpoint, ENDPOINT_FIELDS))
    return endpoint


@transaction.atomic
def update_endpoint(request, endpoint: TlsEndpoint, data: dict, expected) -> TlsEndpoint:
    endpoint = TlsEndpoint.objects.select_for_update().get(pk=endpoint.pk)
    check_version(endpoint, expected)
    if endpoint.retired_at:
        raise ApiError("ENDPOINT_RETIRED", "Retired endpoints cannot be changed.", 409)
    data = _clean_endpoint(data, endpoint)
    merged = {k: data.get(k, getattr(endpoint, k)) for k in ("host", "port", "sni")}
    if _duplicate_endpoint(merged, exclude=endpoint):
        raise _invalid("host", "This host, port and SNI is already an approved endpoint.")
    target_changed = any(merged[k] != getattr(endpoint, k) for k in merged)
    before = _snap(endpoint, ENDPOINT_FIELDS)
    for name in ENDPOINT_FIELDS:
        if name in data:
            setattr(endpoint, name, data[name])
    if target_changed:  # a different target: earlier results no longer describe it
        _close_deployments(endpoint, timezone.now())
        endpoint.current_certificate = None
        endpoint.hostname_matches = None
        endpoint.last_status = TlsEndpoint.CheckStatus.NEVER
        endpoint.last_error = endpoint.last_address = endpoint.tls_version = ""
    endpoint.modified_by = request.user
    endpoint.version = F("version") + 1
    endpoint.save()
    endpoint.refresh_from_db()
    _record(
        request,
        "endpoint.update",
        endpoint,
        before=before,
        after=_snap(endpoint, ENDPOINT_FIELDS),
        detail=data.get("reason", ""),
    )
    return endpoint


@transaction.atomic
def retire_endpoint(request, endpoint: TlsEndpoint, reason: str, expected) -> TlsEndpoint:
    endpoint = TlsEndpoint.objects.select_for_update().get(pk=endpoint.pk)
    check_version(endpoint, expected)
    if endpoint.retired_at:
        raise ApiError("ENDPOINT_RETIRED", "This endpoint is already retired.", 409)
    now = timezone.now()
    _close_deployments(endpoint, now)
    endpoint.retired_at, endpoint.retired_reason = now, reason[:500]
    endpoint.enabled = False
    endpoint.modified_by = request.user
    endpoint.version = F("version") + 1
    endpoint.save()
    endpoint.refresh_from_db()
    _record(request, "endpoint.retire", endpoint, detail=reason)
    return endpoint


def _close_deployments(endpoint, now) -> None:
    CertificateDeployment.objects.filter(endpoint=endpoint, replaced_at__isnull=True).update(
        replaced_at=now
    )


# --- Checks -----------------------------------------------------------------------------------


def check_endpoint(endpoint: TlsEndpoint, now=None) -> TlsEndpoint:
    """Contact one approved endpoint and record what it presented. Failures are recorded on
    the endpoint; the last known certificate and its deployment are kept."""
    now = now or timezone.now()
    status, error, presented, fields = TlsEndpoint.CheckStatus.OK, "", None, None
    try:
        presented = checker.fetch(endpoint.host, endpoint.port, endpoint.sni)
        fields = certs.from_der(presented.der)
    except checker.Blocked as exc:
        status, error = TlsEndpoint.CheckStatus.BLOCKED, str(exc)
    except (checker.CheckFailed, certs.CertificateError) as exc:
        status, error = TlsEndpoint.CheckStatus.FAILED, str(exc)

    with transaction.atomic():
        endpoint = TlsEndpoint.objects.select_for_update().get(pk=endpoint.pk)
        endpoint.last_checked_at, endpoint.last_status, endpoint.last_error = (
            now,
            status,
            error[:500],
        )
        update = ["last_checked_at", "last_status", "last_error"]
        if fields is not None:
            cert, _ = store_certificate(fields, Certificate.Source.OBSERVED, now=now)
            current = CertificateDeployment.objects.filter(
                endpoint=endpoint, replaced_at__isnull=True
            )
            if current.filter(certificate=cert).update(last_seen_at=now) == 0:
                current.update(replaced_at=now)  # rotation: the previous one is replaced
                CertificateDeployment.objects.create(
                    endpoint=endpoint, certificate=cert, first_seen_at=now, last_seen_at=now
                )
            endpoint.current_certificate = cert
            endpoint.hostname_matches = certs.hostname_matches(
                endpoint.sni or endpoint.host, cert.sans, cert.common_name
            )
            endpoint.last_success_at = now
            endpoint.last_address = presented.address
            endpoint.tls_version = presented.tls_version[:20]
            update += [
                "current_certificate",
                "hostname_matches",
                "last_success_at",
                "last_address",
                "tls_version",
            ]
        endpoint.save(update_fields=update)
    return endpoint


def due_endpoints(now=None):
    now = now or timezone.now()
    interval = timedelta(hours=settings.ITAM_TLS_CHECK_INTERVAL_HOURS)
    return TlsEndpoint.objects.filter(enabled=True, retired_at__isnull=True).filter(
        Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=now - interval)
    )


MIN_MANUAL_INTERVAL = timedelta(seconds=60)


def check_now(request, endpoint: TlsEndpoint) -> TlsEndpoint:
    if endpoint.retired_at or not endpoint.enabled:
        raise ApiError("ENDPOINT_DISABLED", "Enable the endpoint before checking it.", 409)
    if endpoint.last_checked_at and timezone.now() - endpoint.last_checked_at < MIN_MANUAL_INTERVAL:
        raise ApiError("CHECK_TOO_SOON", "This endpoint was checked less than a minute ago.", 429)
    endpoint = check_endpoint(endpoint)
    _record(
        request,
        "endpoint.check",
        endpoint,
        after={"status": endpoint.last_status, "error": endpoint.last_error},
    )
    return endpoint
