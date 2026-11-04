"""Domain and approved TLS endpoint import families (docs/11: "Domain | normalized owned FQDN |
owner, registrar, verified expiry" and "TLS endpoint | approved host+port+SNI | asset/service,
owner, enabled"). Certificates themselves are never imported: they are read or uploaded."""

import datetime as dt
import re

from apps.accounts import catalog
from apps.assets.models import Asset
from apps.domains import certs, checker
from apps.domains import services as domain_services
from apps.domains.models import DomainRegistration, TlsEndpoint
from apps.organizations import scope
from config.api import ApiError

from .base import Column, Context, Family, Plan, RowError, check_formulas, text

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T]00:00(?::00)?)?$")
_BOOL = {"yes": True, "true": True, "1": True, "no": False, "false": False, "0": False}


def _date(values: dict, name: str):
    match = _DATE.match(text(values, name, 30))
    if match:
        try:
            return dt.date.fromisoformat(match.group(1))
        except ValueError:
            pass
    raise RowError(f"{name}: use a date like 2027-01-31.")


def _bool(values: dict, name: str):
    raw = text(values, name, 10).lower()
    if raw not in _BOOL:
        raise RowError(f"{name}: use yes or no.")
    return _BOOL[raw]


def _raw(value):
    if isinstance(value, dt.date):
        return value.isoformat()
    if hasattr(value, "pk"):
        return str(value.pk)
    return value


def _api_error(exc: ApiError) -> RowError:
    detail = "; ".join(" ".join(v) for v in exc.field_errors.values())
    return RowError(detail or str(exc.detail))


def _changes(existing, data: dict) -> dict:
    changes = {}
    for field, value in data.items():
        current = getattr(existing, field)
        if current != value:
            changes[field] = {
                "before": str(current) if current not in (None, "") else None,
                "after": str(value),
                "before_raw": _raw(current),
            }
    return changes


class DomainFamily(Family):
    code = "domain"
    label = "Domains"
    version = 1
    description = (
        "Create or update owned domains. An expiry date needs its evidence; without one the "
        "expiry stays Unknown. Rows never retire domains."
    )
    match_help = "Matches on the normalised domain name (lower case, IDNA)."
    permission = catalog.CERTIFICATES_MANAGE
    columns = (
        Column("fqdn", "Domain", "always", "Registered domain name.", "example.org"),
        Column("owner", "Owner", "", "Responsible person or team.", "Web team"),
        Column("registrar", "Registrar", "", "", "Example Registrar Ltd"),
        Column("expires_on", "Registration expires", "", "YYYY-MM-DD.", "2027-03-31"),
        Column(
            "expiry_evidence",
            "Expiry evidence",
            "",
            "Required with an expiry date: where it comes from.",
            "Registrar portal, 2026-11-04",
        ),
        Column("auto_renew", "Auto-renew", "", "yes or no; empty: unknown.", ""),
        Column("note", "Note", "", "", ""),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            try:
                fqdn = certs.normalize_fqdn(text(values, "fqdn", 300))
            except certs.InvalidName as exc:
                raise RowError(f"fqdn: {exc}") from exc
            plan.key = fqdn
            first = ctx.remember(fqdn, row_number)
            if first is not None:
                plan.action = "conflict"
                plan.messages.append(f"Same domain as row {first}.")
                return plan
            data: dict = {}
            for name, limit in (("owner", 200), ("registrar", 200), ("note", 2000)):
                if value := text(values, name, limit):
                    data[name] = value
            if text(values, "expires_on", 30):
                data["expires_on"] = _date(values, "expires_on")
            if value := text(values, "expiry_evidence", 500):
                data["expiry_evidence"] = value
            if text(values, "auto_renew", 10):
                data["auto_renew"] = _bool(values, "auto_renew")
            existing = DomainRegistration.objects.filter(fqdn=fqdn).first()
            evidence = data.get("expiry_evidence", existing.expiry_evidence if existing else "")
            if data.get("expires_on") and not evidence:
                raise RowError("expiry_evidence: required with an expiry date.")
            if existing is None:
                if ctx.mode == "update_matched":
                    plan.action = "skip"
                    plan.messages.append("No matching domain (update only).")
                    return plan
                plan.action, plan.target_label = "create", fqdn
                plan.data = {"fqdn": fqdn, **data}
                plan.changes = {k: {"before": None, "after": str(v)} for k, v in plan.data.items()}
                return plan
            plan.target, plan.target_id, plan.target_label = existing, str(existing.pk), fqdn
            if ctx.mode == "create_only":
                plan.action = "skip"
                plan.messages.append("Exists already (create only).")
                return plan
            if existing.retired_at:
                plan.action = "conflict"
                plan.messages.append("The domain is retired; imports do not change it.")
                return plan
            changes = _changes(existing, data)
            if not changes:
                plan.action = "skip"
                plan.messages.append("Unchanged.")
                return plan
            plan.action, plan.changes = "update", changes
            plan.data = {k: data[k] for k in changes}
            return plan
        except RowError as exc:
            plan.messages.append(str(exc))
            return plan

    def apply(self, ctx: Context, plan: Plan, values: dict):
        try:
            if plan.action == "create":
                domain = domain_services.create_domain(ctx.request, plan.data)
            else:
                domain = domain_services.update_domain(
                    ctx.request,
                    plan.target,
                    {**plan.data, "reason": f"Imported from {ctx.job.filename}"},
                    plan.target.version,
                )
        except ApiError as exc:
            raise _api_error(exc) from exc
        return str(domain.pk), domain.fqdn, domain.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        domain = DomainRegistration.objects.filter(pk=row.target_id).first()
        if domain is None or domain.version != row.version_after:
            return False, "The domain changed after the import; correct it by hand."
        reason = f"Rollback of import {ctx.job.pk}"
        if row.action == "create":
            domain_services.retire_domain(ctx.request, domain, reason, domain.version)
            return True, "Retired (created by the import)."
        restore = {}
        for field, change in row.changes.items():
            raw = change.get("before_raw")
            if field == "expires_on":
                restore[field] = dt.date.fromisoformat(raw) if raw else None
            elif field == "auto_renew":
                restore[field] = raw
            else:
                restore[field] = raw or ""
        restore["reason"] = reason
        domain_services.update_domain(ctx.request, domain, restore, domain.version)
        return True, "Previous values restored."


class TlsEndpointFamily(Family):
    code = "tls_endpoint"
    label = "Approved TLS endpoints"
    version = 1
    description = (
        "Approve hosts and ports ITAM may contact to read the presented certificate. Names "
        "only (no URLs); metadata and link-local addresses are refused. Rows never retire "
        "endpoints."
    )
    match_help = "Matches on host + port + SNI among endpoints that are not retired."
    permission = catalog.CERTIFICATES_MANAGE
    columns = (
        Column("host", "Host", "always", "Host name or IP address.", "intranet.example.org"),
        Column("port", "Port", "", "Default 443.", "443"),
        Column("sni", "SNI", "", "Server name to present; default: the host name.", ""),
        Column("asset_tag", "Asset tag", "", "Asset in your sites that serves it.", ""),
        Column("service", "Service", "", "", "Intranet"),
        Column("owner", "Owner", "", "", "Web team"),
        Column("enabled", "Checked", "", "yes or no; default yes.", "yes"),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            try:
                host = certs.normalize_host(text(values, "host", 300))
            except certs.InvalidName as exc:
                raise RowError(f"host: {exc}") from exc
            if certs.is_ip(host) and (reason := checker.refused(host)):
                raise RowError(f"host: ITAM does not connect to this address ({reason}).")
            port = 443
            if raw := text(values, "port", 6):
                if not raw.isdigit() or not 1 <= int(raw) <= 65535:
                    raise RowError("port: a number from 1 to 65535.")
                port = int(raw)
            sni = text(values, "sni", 300)
            if sni:
                try:
                    sni = certs.normalize_fqdn(sni)
                except certs.InvalidName as exc:
                    raise RowError(f"sni: {exc}") from exc
            elif not certs.is_ip(host):
                sni = host
            plan.key = f"{host}:{port}:{sni}"
            first = ctx.remember(plan.key, row_number)
            if first is not None:
                plan.action = "conflict"
                plan.messages.append(f"Same endpoint as row {first}.")
                return plan
            data: dict = {}
            for name, limit in (("service", 200), ("owner", 200)):
                if value := text(values, name, limit):
                    data[name] = value
            if text(values, "enabled", 10):
                data["enabled"] = _bool(values, "enabled")
            if tag := text(values, "asset_tag", 100):
                visible = scope.restrict(Asset.objects.all(), ctx.user, field="site")
                asset = visible.filter(asset_tag__iexact=tag, archived_at__isnull=True).first()
                if asset is None:
                    raise RowError(f"asset_tag: no asset {tag!r} in your sites.")
                data["asset"] = asset
            existing = TlsEndpoint.objects.filter(
                host=host, port=port, sni=sni, retired_at__isnull=True
            ).first()
            if existing is None:
                if ctx.mode == "update_matched":
                    plan.action = "skip"
                    plan.messages.append("No matching endpoint (update only).")
                    return plan
                plan.action, plan.target_label = "create", plan.key
                plan.data = {"host": host, "port": port, "sni": sni, **data}
                plan.changes = {k: {"before": None, "after": str(v)} for k, v in plan.data.items()}
                return plan
            plan.target, plan.target_id, plan.target_label = existing, str(existing.pk), plan.key
            if ctx.mode == "create_only":
                plan.action = "skip"
                plan.messages.append("Exists already (create only).")
                return plan
            changes = _changes(existing, data)
            if not changes:
                plan.action = "skip"
                plan.messages.append("Unchanged.")
                return plan
            plan.action, plan.changes = "update", changes
            plan.data = {k: data[k] for k in changes}
            return plan
        except RowError as exc:
            plan.messages.append(str(exc))
            return plan

    def apply(self, ctx: Context, plan: Plan, values: dict):
        try:
            if plan.action == "create":
                endpoint = domain_services.create_endpoint(ctx.request, plan.data)
            else:
                endpoint = domain_services.update_endpoint(
                    ctx.request,
                    plan.target,
                    {**plan.data, "reason": f"Imported from {ctx.job.filename}"},
                    plan.target.version,
                )
        except ApiError as exc:
            raise _api_error(exc) from exc
        return str(endpoint.pk), str(endpoint), endpoint.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        endpoint = TlsEndpoint.objects.filter(pk=row.target_id, retired_at__isnull=True).first()
        if endpoint is None or endpoint.version != row.version_after:
            return False, "The endpoint changed after the import; correct it by hand."
        reason = f"Rollback of import {ctx.job.pk}"
        if row.action == "create":
            domain_services.retire_endpoint(ctx.request, endpoint, reason, endpoint.version)
            return True, "Retired (created by the import)."
        restore = {}
        for field, change in row.changes.items():
            raw = change.get("before_raw")
            if field == "asset":
                restore[field] = Asset.objects.filter(pk=raw).first() if raw else None
            elif field == "enabled":
                restore[field] = raw
            else:
                restore[field] = raw or ""
        restore["reason"] = reason
        domain_services.update_endpoint(ctx.request, endpoint, restore, endpoint.version)
        return True, "Previous values restored."
