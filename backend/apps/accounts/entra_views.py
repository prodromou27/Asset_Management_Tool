"""Small browser-facing OIDC endpoints; tokens and provider errors never leave the server."""

from authlib.common.errors import AuthlibBaseError
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from joserfc.errors import JoseError
from requests.exceptions import RequestException
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditEvent
from apps.integrations.secrets import SecretError
from config.api import ApiError, require_if_match

from . import oidc
from .catalog import USERS_MANAGE
from .models import User
from .permissions import HasPermission
from .serializers import UserSerializer


class AuthorizationSerializer(serializers.Serializer):
    authorization_url = serializers.URLField(read_only=True)


class BindingSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField(allow_null=True)
    object_id = serializers.UUIDField(allow_null=True)

    def validate(self, attrs):
        user = self.context.get("user")
        attrs = {
            "tenant_id": attrs.get("tenant_id", getattr(user, "entra_tenant_id", None)),
            "object_id": attrs.get("object_id", getattr(user, "entra_object_id", None)),
        }
        if (attrs["tenant_id"] is None) != (attrs["object_id"] is None):
            raise serializers.ValidationError(
                "Tenant and object IDs must both be set or both cleared."
            )
        return attrs


class StartSerializer(serializers.Serializer):
    next_path = serializers.CharField(max_length=2048, default="/", trim_whitespace=False)

    def validate_next_path(self, value):
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        ):
            raise serializers.ValidationError("Use a local application path.")
        return value


@method_decorator(csrf_protect, name="dispatch")
class EntraStartView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=StartSerializer, responses=AuthorizationSerializer)
    def post(self, request):
        data = StartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            url = oidc.start(request, **data.validated_data)
        except (oidc.OidcFailure, SecretError, ValueError, TypeError):
            raise ApiError(
                "SSO_NOT_READY",
                "Microsoft Entra sign-in is not ready. Contact your administrator.",
                503,
            ) from None
        response = Response({"authorization_url": url})
        response["Cache-Control"] = "no-store"
        return response


class EntraCallbackView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(responses={302: None})
    def get(self, request):
        try:
            _, next_path = oidc.finish(request)
        except (
            oidc.OidcFailure,
            SecretError,
            AuthlibBaseError,
            JoseError,
            RequestException,
            ValueError,
            TypeError,
            KeyError,
        ):
            audit.record(
                action="auth.entra_failed",
                actor_label="entra",
                object_type="authentication",
                outcome=AuditEvent.Outcome.FAILURE,
                request=request,
                detail="Entra sign-in could not be verified",
            )
            response = HttpResponseRedirect("/login?sso_error=1")
        else:
            response = HttpResponseRedirect(next_path)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class EntraBindingView(APIView):
    permission_classes = [HasPermission(USERS_MANAGE)]

    @extend_schema(
        request=BindingSerializer,
        responses=UserSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        from django.shortcuts import get_object_or_404

        from .entra_admin import bind_identity

        user = get_object_or_404(User, pk=pk)
        require_if_match(request, user.version)
        data = BindingSerializer(data=request.data, partial=True, context={"user": user})
        data.is_valid(raise_exception=True)
        user = bind_identity(request, user, **data.validated_data)
        return Response(UserSerializer(user).data, headers={"ETag": f'"{user.version}"'})
