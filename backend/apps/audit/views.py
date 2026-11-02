from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from config.api import ApiError, ItemsCursorPagination

from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditPagination(ItemsCursorPagination):
    ordering = "-occurred_at"


def _parse_instant(value: str, name: str):
    parsed = parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise ApiError(
            "VALIDATION_ERROR",
            "The submitted data is invalid.",
            422,
            {name: ["Use an RFC 3339 timestamp with a UTC offset."]},
        )
    return parsed


@extend_schema(
    parameters=[
        OpenApiParameter("action", str, description="Exact action code, e.g. users.disable"),
        OpenApiParameter("actor", str, description="Actor username (exact)"),
        OpenApiParameter("object_type", str),
        OpenApiParameter("object_id", str),
        OpenApiParameter("outcome", str, enum=["success", "failure", "denied"]),
        OpenApiParameter("from", str, description="RFC 3339 lower bound (inclusive)"),
        OpenApiParameter("to", str, description="RFC 3339 upper bound (exclusive)"),
    ]
)
class AuditEventListView(generics.ListAPIView):
    serializer_class = AuditEventSerializer
    pagination_class = AuditPagination
    permission_classes = [HasPermission(catalog.AUDIT_VIEW)]

    def get_queryset(self):
        qs = AuditEvent.objects.all()
        params = self.request.query_params
        for field in ("action", "object_type", "object_id", "outcome"):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        if actor := params.get("actor"):
            qs = qs.filter(actor_label=actor.strip().lower())
        if value := params.get("from"):
            qs = qs.filter(occurred_at__gte=_parse_instant(value, "from"))
        if value := params.get("to"):
            qs = qs.filter(occurred_at__lt=_parse_instant(value, "to"))
        return qs
