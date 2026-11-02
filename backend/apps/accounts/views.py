from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.api import ItemsCursorPagination, require_if_match

from . import catalog, services
from .models import Permission, Role, SecuritySettings, User
from .permissions import HasMethodPermission, HasPermission
from .serializers import (
    AuthProviderSerializer,
    ChangePasswordSerializer,
    DisableUserSerializer,
    LoginSerializer,
    MeSerializer,
    PermissionSerializer,
    ResetPasswordSerializer,
    RoleSerializer,
    SecuritySettingsSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

# --- Auth -------------------------------------------------------------------


class CsrfView(APIView):
    """Sets the CSRF cookie so the SPA can send X-CSRFToken on unsafe requests."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={204: None})
    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class LocalLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer})
    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.login_local(
            request, data.validated_data["username"], data.validated_data["password"]
        )
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        services.logout_session(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_change"

    @extend_schema(request=ChangePasswordSerializer, responses={204: None})
    def post(self, request):
        data = ChangePasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.change_own_password(
            request, data.validated_data["current_password"], data.validated_data["new_password"]
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProvidersView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses=AuthProviderSerializer(many=True))
    def get(self, request):
        providers = [
            {"id": "local", "kind": "local", "label": "Local account", "status": "available"},
            {"id": "entra", "kind": "oidc", "label": "Microsoft Entra ID", "status": "planned"},
        ]
        return Response(AuthProviderSerializer(providers, many=True).data)


# --- Users ------------------------------------------------------------------


class UserPagination(ItemsCursorPagination):
    ordering = "username"


@extend_schema(
    parameters=[
        OpenApiParameter("q", str, description="Match username, display name or email"),
        OpenApiParameter("status", str, enum=["active", "disabled", "locked"]),
        OpenApiParameter("role", str, description="Role code"),
    ]
)
class UserListCreateView(generics.ListAPIView):
    serializer_class = UserSerializer
    pagination_class = UserPagination
    permission_classes = [HasMethodPermission(catalog.USERS_VIEW, catalog.USERS_MANAGE)]

    def get_queryset(self):
        from django.utils import timezone

        qs = User.objects.prefetch_related("roles").select_related("disabled_by", "created_by")
        params = self.request.query_params
        if q := params.get("q", "").strip():
            qs = qs.filter(
                Q(username__icontains=q) | Q(display_name__icontains=q) | Q(email__icontains=q)
            )
        match params.get("status"):
            case "active":
                qs = qs.filter(is_active=True)
            case "disabled":
                qs = qs.filter(is_active=False)
            case "locked":
                qs = qs.filter(locked_until__gt=timezone.now())
        if role := params.get("role"):
            qs = qs.filter(roles__code=role)
        return qs.distinct()

    @extend_schema(request=UserCreateSerializer, responses={201: UserSerializer})
    def post(self, request):
        data = UserCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.create_user(request, **data.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [HasMethodPermission(catalog.USERS_VIEW, catalog.USERS_MANAGE)]

    def _get(self, pk):
        return generics.get_object_or_404(User.objects.prefetch_related("roles"), pk=pk)

    @extend_schema(responses=UserSerializer)
    def get(self, request, pk):
        user = self._get(pk)
        return Response(UserSerializer(user).data, headers={"ETag": f'"{user.version}"'})

    @extend_schema(
        request=UserUpdateSerializer,
        responses=UserSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        user = self._get(pk)
        require_if_match(request, user.version)
        data = UserUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        user = services.update_user(request, user, data.validated_data)
        return Response(UserSerializer(user).data, headers={"ETag": f'"{user.version}"'})


class _UserActionView(APIView):
    permission_classes = [HasPermission(catalog.USERS_MANAGE)]

    def get_user(self, pk):
        return generics.get_object_or_404(User, pk=pk)


class DisableUserView(_UserActionView):
    @extend_schema(request=DisableUserSerializer, responses=UserSerializer)
    def post(self, request, pk):
        data = DisableUserSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.disable_user(request, self.get_user(pk), data.validated_data["reason"])
        return Response(UserSerializer(user).data)


class EnableUserView(_UserActionView):
    @extend_schema(request=None, responses=UserSerializer)
    def post(self, request, pk):
        return Response(UserSerializer(services.enable_user(request, self.get_user(pk))).data)


class UnlockUserView(_UserActionView):
    @extend_schema(request=None, responses=UserSerializer)
    def post(self, request, pk):
        return Response(UserSerializer(services.unlock_user(request, self.get_user(pk))).data)


class ResetPasswordView(_UserActionView):
    @extend_schema(request=ResetPasswordSerializer, responses=UserSerializer)
    def post(self, request, pk):
        data = ResetPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.reset_password(request, self.get_user(pk), data.validated_data["password"])
        return Response(UserSerializer(user).data)


# --- Roles / permissions ----------------------------------------------------


class RoleListView(generics.ListAPIView):
    serializer_class = RoleSerializer
    pagination_class = None
    permission_classes = [HasPermission(catalog.ROLES_VIEW)]
    queryset = Role.objects.prefetch_related("permissions")


class PermissionListView(generics.ListAPIView):
    serializer_class = PermissionSerializer
    pagination_class = None
    permission_classes = [HasPermission(catalog.ROLES_VIEW)]
    queryset = Permission.objects.all()


# --- Settings ---------------------------------------------------------------


class SecuritySettingsView(APIView):
    permission_classes = [
        HasMethodPermission(catalog.SECURITY_SETTINGS_VIEW, catalog.SECURITY_SETTINGS_MANAGE)
    ]

    @extend_schema(responses=SecuritySettingsSerializer)
    def get(self, request):
        policy = SecuritySettings.load()
        return Response(
            SecuritySettingsSerializer(policy).data, headers={"ETag": f'"{policy.version}"'}
        )

    @extend_schema(
        request=inline_serializer(
            "SecuritySettingsUpdate",
            {field: serializers.IntegerField(required=False) for field in services.SECURITY_FIELDS},
        ),
        responses=SecuritySettingsSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request):
        policy = SecuritySettings.load()
        require_if_match(request, policy.version)
        data = SecuritySettingsSerializer(policy, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        policy = services.update_security_settings(request, data.validated_data)
        return Response(
            SecuritySettingsSerializer(policy).data, headers={"ETag": f'"{policy.version}"'}
        )
