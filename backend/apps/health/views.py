from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPermission

from . import services
from .operations import collect_operations
from .serializers import LivenessSerializer, OperationalHealthSerializer, ReadinessSerializer


class LivenessView(APIView):
    """Process is up and able to serve requests. No dependency checks."""

    permission_classes = [AllowAny]

    @extend_schema(responses=LivenessSerializer)
    def get(self, request):
        return Response({"status": "ok"})


class OperationalHealthView(APIView):
    permission_classes = [HasPermission("health.view")]

    @extend_schema(responses=OperationalHealthSerializer)
    def get(self, request):
        return Response(
            OperationalHealthSerializer(collect_operations()).data,
            headers={"Cache-Control": "no-store"},
        )


class ReadinessView(APIView):
    """Process and its required dependencies (DB, Redis) are reachable."""

    permission_classes = [AllowAny]

    @extend_schema(responses=ReadinessSerializer)
    def get(self, request):
        statuses = services.collect_dependency_statuses()
        dependencies = {
            status.name: {"status": "up" if status.healthy else "down", "detail": status.detail}
            for status in statuses
        }
        all_healthy = all(status.healthy for status in statuses)
        body = {"status": "ok" if all_healthy else "degraded", "dependencies": dependencies}
        return Response(body, status=200 if all_healthy else 503)
