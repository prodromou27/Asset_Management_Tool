from rest_framework import serializers


class LivenessSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok"])


class DependencyStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["up", "down"])
    detail = serializers.CharField(allow_blank=True)


class ReadinessSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    dependencies = serializers.DictField(child=DependencyStatusSerializer())
