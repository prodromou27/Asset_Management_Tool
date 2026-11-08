from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .local_mfa import manage
from .permissions import IsAuthenticatedWithCurrentPassword


class MfaRequestSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    otp_code = serializers.CharField(max_length=64, allow_blank=True, default="", write_only=True)


class MfaSetupSerializer(serializers.Serializer):
    secret = serializers.CharField(read_only=True)
    provisioning_uri = serializers.CharField(read_only=True)


class MfaRecoverySerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField(), read_only=True)


class MfaSetupView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_change"
    action = "setup"

    def perform(self, request):
        data = MfaRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        response = Response(
            manage(
                request,
                self.action,
                **{
                    "password": data.validated_data["password"],
                    "code": data.validated_data["otp_code"],
                },
            )
        )
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response

    @extend_schema(request=MfaRequestSerializer, responses=MfaSetupSerializer)
    def post(self, request):
        return self.perform(request)


class MfaConfirmView(MfaSetupView):
    action = "confirm"

    @extend_schema(request=MfaRequestSerializer, responses=MfaRecoverySerializer)
    def post(self, request):
        return self.perform(request)


class MfaDisableView(MfaSetupView):
    action = "disable"

    @extend_schema(request=MfaRequestSerializer, responses={200: None})
    def post(self, request):
        return self.perform(request)
