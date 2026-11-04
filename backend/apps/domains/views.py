"""Domains and certificates API (docs/04: /domains, /certificates, /certificates/deployments,
/tls-endpoints; /assets/{id}/certificates).

Reading needs ``certificates.view``; changes need ``certificates.manage``. Domains,
certificates and endpoints are organisation-wide; an endpoint's linked asset is shown only to
people who can see that asset, and linking needs the asset in the caller's sites.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer
from apps.organizations.scope import ALL, accessible_site_ids
from config.api import ItemsCursorPagination

from . import certs, services
from .models import Certificate, CertificateDeployment, DomainRegistration, TlsEndpoint

View = HasPermission(catalog.CERTIFICATES_VIEW)
Manage = HasPermission(catalog.CERTIFICATES_VIEW, catalog.CERTIFICATES_MANAGE)
EXPIRY_STATES = ["unknown", "ok", "expiring", "expired"]


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _expiry_window(qs, field: str, state: str, today):
    """Filter by expiry state using the warning window (largest threshold)."""
    window = today + timedelta(days=max(certs.warning_days()))
    if state == "unknown":
        return qs.filter(**{f"{field}__isnull": True})
    if state == "expired":
        return qs.filter(**{f"{field}__lt": today})
    if state == "expiring":
        return qs.filter(**{f"{field}__gte": today, f"{field}__lte": window})
    if state == "ok":
        return qs.filter(**{f"{field}__gt": window})
    return qs


# --- Serializers ------------------------------------------------------------------------------


class ExpirySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=EXPIRY_STATES)
    days_remaining = serializers.IntegerField(allow_null=True)
    threshold = serializers.IntegerField(allow_null=True, help_text="Warning threshold reached")


def _expiry(end, context) -> dict:
    e = certs.expiry(end, context.get("today") or services.today_utc())
    return {"status": e.status, "days_remaining": e.days_remaining, "threshold": e.threshold}


class DomainSerializer(serializers.ModelSerializer):
    expiry = serializers.SerializerMethodField()
    expiry_verified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = DomainRegistration
        fields = [
            "id",
            "fqdn",
            "owner",
            "registrar",
            "expires_on",
            "expiry_evidence",
            "expiry_verified_by",
            "expiry_verified_at",
            "expiry",
            "auto_renew",
            "note",
            "retired_at",
            "retired_reason",
            "version",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields

    @extend_schema_field(ExpirySerializer)
    def get_expiry(self, obj):
        return _expiry(obj.expires_on, self.context)


class DomainWriteSerializer(serializers.Serializer):
    fqdn = serializers.CharField(max_length=300)
    owner = serializers.CharField(max_length=200, allow_blank=True, required=False)
    registrar = serializers.CharField(max_length=200, allow_blank=True, required=False)
    expires_on = serializers.DateField(allow_null=True, required=False)
    expiry_evidence = serializers.CharField(max_length=500, allow_blank=True, required=False)
    auto_renew = serializers.BooleanField(allow_null=True, required=False)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False)


class CertificateSerializer(serializers.ModelSerializer):
    expiry = serializers.SerializerMethodField()
    sans = serializers.ListField(child=serializers.CharField(), read_only=True)
    endpoints = serializers.IntegerField(
        read_only=True, help_text="Approved endpoints currently presenting it"
    )

    class Meta:
        model = Certificate
        fields = [
            "id",
            "fingerprint_sha256",
            "subject",
            "common_name",
            "issuer",
            "serial_number",
            "sans",
            "not_before",
            "not_after",
            "expiry",
            "signature_algorithm",
            "public_key",
            "self_signed",
            "is_ca",
            "source",
            "first_seen_at",
            "endpoints",
            "note",
        ]
        read_only_fields = fields

    @extend_schema_field(ExpirySerializer)
    def get_expiry(self, obj):
        return _expiry(obj.not_after, self.context)


class TlsAssetRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site_code = serializers.CharField()


class CertificateRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    common_name = serializers.CharField()
    fingerprint_sha256 = serializers.CharField()
    not_after = serializers.DateTimeField()
    expiry = ExpirySerializer()


def _cert_ref(cert, context):
    if cert is None:
        return None
    return {
        "id": cert.pk,
        "common_name": cert.common_name,
        "fingerprint_sha256": cert.fingerprint_sha256,
        "not_after": cert.not_after,
        "expiry": _expiry(cert.not_after, context),
    }


class TlsEndpointSerializer(serializers.ModelSerializer):
    asset = serializers.SerializerMethodField()
    asset_hidden = serializers.SerializerMethodField(
        help_text="Linked to an asset outside your sites"
    )
    certificate = serializers.SerializerMethodField()

    class Meta:
        model = TlsEndpoint
        fields = [
            "id",
            "host",
            "port",
            "sni",
            "asset",
            "asset_hidden",
            "service",
            "owner",
            "enabled",
            "note",
            "certificate",
            "hostname_matches",
            "last_checked_at",
            "last_success_at",
            "last_status",
            "last_error",
            "last_address",
            "tls_version",
            "retired_at",
            "retired_reason",
            "version",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields

    def _visible(self, obj) -> bool:
        scope = self.context.get("scope", ALL)
        return obj.asset_id is not None and (scope is ALL or obj.asset.site_id in scope)

    @extend_schema_field(TlsAssetRefSerializer(allow_null=True))
    def get_asset(self, obj):
        if not self._visible(obj):
            return None
        return {"id": obj.asset_id, "name": obj.asset.name, "site_code": obj.asset.site.code}

    def get_asset_hidden(self, obj) -> bool:
        return obj.asset_id is not None and not self._visible(obj)

    @extend_schema_field(CertificateRefSerializer(allow_null=True))
    def get_certificate(self, obj):
        return _cert_ref(obj.current_certificate, self.context)


class TlsEndpointWriteSerializer(serializers.Serializer):
    host = serializers.CharField(max_length=300)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    sni = serializers.CharField(max_length=300, allow_blank=True, required=False)
    asset = serializers.UUIDField(allow_null=True, required=False)
    service = serializers.CharField(max_length=200, allow_blank=True, required=False)
    owner = serializers.CharField(max_length=200, allow_blank=True, required=False)
    enabled = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False)


class DeploymentEndpointRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField()
    service = serializers.CharField()
    retired = serializers.BooleanField()


class DeploymentSerializer(serializers.ModelSerializer):
    endpoint = serializers.SerializerMethodField()
    certificate = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()

    class Meta:
        model = CertificateDeployment
        fields = [
            "id",
            "endpoint",
            "certificate",
            "first_seen_at",
            "last_seen_at",
            "replaced_at",
            "current",
        ]
        read_only_fields = fields

    @extend_schema_field(DeploymentEndpointRefSerializer)
    def get_endpoint(self, obj):
        e = obj.endpoint
        return {
            "id": e.pk,
            "label": str(e),
            "service": e.service,
            "retired": e.retired_at is not None,
        }

    @extend_schema_field(CertificateRefSerializer)
    def get_certificate(self, obj):
        return _cert_ref(obj.certificate, self.context)

    def get_current(self, obj) -> bool:
        return obj.replaced_at is None and obj.endpoint.retired_at is None


class CertificateDetailSerializer(CertificateSerializer):
    pem = serializers.CharField(read_only=True)
    deployments = DeploymentSerializer(many=True, read_only=True)

    class Meta(CertificateSerializer.Meta):
        fields = [*CertificateSerializer.Meta.fields, "pem", "deployments"]
        read_only_fields = fields


class CertificateUploadSerializer(serializers.Serializer):
    pem = serializers.CharField(max_length=100_000)
    note = serializers.CharField(max_length=500, allow_blank=True, required=False)


# --- Domains ----------------------------------------------------------------------------------


class DomainPagination(ItemsCursorPagination):
    ordering = ("fqdn", "id")


class DomainListView(generics.ListCreateAPIView):
    serializer_class = DomainSerializer
    pagination_class = DomainPagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Domain, owner or registrar"),
            OpenApiParameter("expiry", str, enum=EXPIRY_STATES),
            OpenApiParameter("include_retired", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = DomainRegistration.objects.select_related("expiry_verified_by")
        if params.get("include_retired") not in ("true", "1"):
            qs = qs.filter(retired_at__isnull=True)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(fqdn__icontains=q.lower()) | Q(owner__icontains=q) | Q(registrar__icontains=q)
            )
        return _expiry_window(qs, "expires_on", params.get("expiry", ""), services.today_utc())

    @extend_schema(request=DomainWriteSerializer, responses={201: DomainSerializer})
    def post(self, request, *args, **kwargs):
        data = DomainWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("reason", None)
        domain = services.create_domain(request, values)
        return Response(
            DomainSerializer(domain).data,
            status=status.HTTP_201_CREATED,
            headers={"ETag": f'"{domain.version}"'},
        )


class DomainDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=DomainSerializer)
    def get(self, request, pk):
        domain = get_object_or_404(DomainRegistration, pk=pk)
        return Response(DomainSerializer(domain).data, headers={"ETag": f'"{domain.version}"'})

    @extend_schema(request=DomainWriteSerializer, responses=DomainSerializer, parameters=[IF_MATCH])
    def patch(self, request, pk):
        domain = get_object_or_404(DomainRegistration, pk=pk)
        data = DomainWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        domain = services.update_domain(request, domain, data.validated_data, _if_match(request))
        return Response(DomainSerializer(domain).data, headers={"ETag": f'"{domain.version}"'})


class DomainRetireView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses=DomainSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        domain = get_object_or_404(DomainRegistration, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        domain = services.retire_domain(
            request, domain, data.validated_data["reason"], _if_match(request)
        )
        return Response(DomainSerializer(domain).data)


# --- Certificates -----------------------------------------------------------------------------


def certificates_qs():
    return Certificate.objects.annotate(
        endpoints=Count(
            "deployments",
            filter=Q(
                deployments__replaced_at__isnull=True,
                deployments__endpoint__retired_at__isnull=True,
            ),
            distinct=True,
        )
    )


class CertificatePagination(ItemsCursorPagination):
    ordering = ("not_after", "id")


class CertificateListView(generics.ListCreateAPIView):
    serializer_class = CertificateSerializer
    pagination_class = CertificatePagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Name, SAN, issuer or fingerprint"),
            OpenApiParameter("expiry", str, enum=EXPIRY_STATES),
            OpenApiParameter("deployed", bool, description="Only certificates on an endpoint"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = certificates_qs()
        if q := params.get("q", "").strip()[:100]:
            fingerprint = q.lower().replace(":", "")
            qs = qs.filter(
                Q(common_name__icontains=q)
                | Q(subject__icontains=q)
                | Q(issuer__icontains=q)
                | Q(sans__icontains=q.lower())
                | Q(fingerprint_sha256__startswith=fingerprint)
            )
        if params.get("deployed") in ("true", "1"):
            qs = qs.filter(endpoints__gt=0)
        state = params.get("expiry", "")
        if state:
            today = services.today_utc()
            if state == "expired":
                qs = qs.filter(not_after__lt=datetime.combine(today, time.min, UTC))
            else:
                start = datetime.combine(today, time.min, UTC)
                end = datetime.combine(
                    today + timedelta(days=max(certs.warning_days()) + 1), time.min, UTC
                )
                if state == "expiring":
                    qs = qs.filter(not_after__gte=start, not_after__lt=end)
                elif state == "ok":
                    qs = qs.filter(not_after__gte=end)
                else:
                    qs = qs.none()
        return qs

    @extend_schema(
        request=CertificateUploadSerializer, responses={201: CertificateSerializer(many=True)}
    )
    def post(self, request, *args, **kwargs):
        data = CertificateUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        stored = services.upload_certificates(
            request, data.validated_data["pem"], data.validated_data.get("note", "")
        )
        rows = certificates_qs().filter(pk__in=[c.pk for c in stored])
        return Response(CertificateSerializer(rows, many=True).data, status=status.HTTP_201_CREATED)


class CertificateDetailView(APIView):
    permission_classes = [View]

    @extend_schema(responses=CertificateDetailSerializer)
    def get(self, request, pk):
        cert = get_object_or_404(certificates_qs(), pk=pk)
        data = CertificateSerializer(cert).data
        data["pem"] = cert.pem
        data["deployments"] = DeploymentSerializer(
            cert.deployments.select_related("endpoint", "certificate").order_by("-last_seen_at"),
            many=True,
        ).data
        return Response(data)


class DeploymentPagination(ItemsCursorPagination):
    ordering = ("-last_seen_at", "-id")


class DeploymentListView(generics.ListAPIView):
    """docs/04 GET /certificates/deployments: certificate observations per endpoint."""

    serializer_class = DeploymentSerializer
    pagination_class = DeploymentPagination
    permission_classes = [View]

    @extend_schema(
        parameters=[
            OpenApiParameter("endpoint", str),
            OpenApiParameter("certificate", str),
            OpenApiParameter("current", bool, description="Only certificates still presented"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = CertificateDeployment.objects.select_related("endpoint", "certificate")
        for name in ("endpoint", "certificate"):
            if value := params.get(name):
                ident = _uuid(value)
                qs = qs.filter(**{f"{name}_id": ident}) if ident else qs.none()
        if params.get("current") in ("true", "1"):
            qs = qs.filter(replaced_at__isnull=True, endpoint__retired_at__isnull=True)
        return qs


# --- TLS endpoints ----------------------------------------------------------------------------


def _endpoint_context(request) -> dict:
    return {"scope": accessible_site_ids(request.user), "today": services.today_utc()}


def _endpoint_response(request, endpoint, http_status=status.HTTP_200_OK):
    endpoint = TlsEndpoint.objects.select_related("asset__site", "current_certificate").get(
        pk=endpoint.pk
    )
    return Response(
        TlsEndpointSerializer(endpoint, context=_endpoint_context(request)).data,
        status=http_status,
        headers={"ETag": f'"{endpoint.version}"'},
    )


def _resolve_asset(request, values: dict) -> dict:
    if "asset" in values and values["asset"] is not None:
        values["asset"] = get_object_or_404(
            visible_assets(request.user).filter(archived_at__isnull=True), pk=values["asset"]
        )
    return values


class EndpointPagination(ItemsCursorPagination):
    ordering = ("host", "port", "id")


class TlsEndpointListView(generics.ListCreateAPIView):
    serializer_class = TlsEndpointSerializer
    pagination_class = EndpointPagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Host, SNI, service or owner"),
            OpenApiParameter("status", str, enum=[s for s, _ in TlsEndpoint.CheckStatus.choices]),
            OpenApiParameter("asset", str),
            OpenApiParameter("include_retired", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), **_endpoint_context(self.request)}

    def get_queryset(self):
        params = self.request.query_params
        qs = TlsEndpoint.objects.select_related("asset__site", "current_certificate")
        if params.get("include_retired") not in ("true", "1"):
            qs = qs.filter(retired_at__isnull=True)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(host__icontains=q.lower())
                | Q(sni__icontains=q.lower())
                | Q(service__icontains=q)
                | Q(owner__icontains=q)
            )
        if value := params.get("status"):
            qs = qs.filter(last_status=value)
        if value := params.get("asset"):
            ident = _uuid(value)
            visible = visible_assets(self.request.user).values("pk")
            qs = qs.filter(asset_id=ident, asset__in=visible) if ident else qs.none()
        return qs

    @extend_schema(request=TlsEndpointWriteSerializer, responses={201: TlsEndpointSerializer})
    def post(self, request, *args, **kwargs):
        data = TlsEndpointWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = _resolve_asset(request, dict(data.validated_data))
        values.pop("reason", None)
        endpoint = services.create_endpoint(request, values)
        return _endpoint_response(request, endpoint, status.HTTP_201_CREATED)


class TlsEndpointDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=TlsEndpointSerializer)
    def get(self, request, pk):
        return _endpoint_response(request, get_object_or_404(TlsEndpoint, pk=pk))

    @extend_schema(
        request=TlsEndpointWriteSerializer, responses=TlsEndpointSerializer, parameters=[IF_MATCH]
    )
    def patch(self, request, pk):
        endpoint = get_object_or_404(TlsEndpoint, pk=pk)
        data = TlsEndpointWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = _resolve_asset(request, dict(data.validated_data))
        if (
            "asset" in values
            and endpoint.asset_id
            and not visible_assets(request.user).filter(pk=endpoint.asset_id).exists()
        ):
            raise serializers.ValidationError(
                {"asset": ["The current asset is outside your sites; ask someone who can see it."]}
            )
        endpoint = services.update_endpoint(request, endpoint, values, _if_match(request))
        return _endpoint_response(request, endpoint)


class TlsEndpointRetireView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses=TlsEndpointSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        endpoint = get_object_or_404(TlsEndpoint, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        endpoint = services.retire_endpoint(
            request, endpoint, data.validated_data["reason"], _if_match(request)
        )
        return _endpoint_response(request, endpoint)


class TlsEndpointCheckView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=None, responses=TlsEndpointSerializer)
    def post(self, request, pk):
        endpoint = get_object_or_404(TlsEndpoint, pk=pk)
        endpoint = services.check_now(request, endpoint)
        return _endpoint_response(request, endpoint)


class AssetCertificatesView(APIView):
    """docs/04 GET /assets/{id}/certificates: endpoints linked to the asset with the
    certificate each currently presents."""

    permission_classes = [HasPermission(catalog.ASSETS_VIEW, catalog.CERTIFICATES_VIEW)]

    @extend_schema(responses=TlsEndpointSerializer(many=True))
    def get(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        rows = TlsEndpoint.objects.filter(asset=asset, retired_at__isnull=True).select_related(
            "asset__site", "current_certificate"
        )
        return Response(
            TlsEndpointSerializer(rows, many=True, context=_endpoint_context(request)).data
        )
