from rest_framework import serializers


class LivenessSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok"])


class DependencyStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["up", "down"])
    detail = serializers.CharField(allow_blank=True)


class ReadinessSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    dependencies = serializers.DictField(child=DependencyStatusSerializer())


class OperationalCheckSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    status = serializers.ChoiceField(
        choices=["up", "down", "unknown", "disabled", "needs_attention"]
    )
    detail = serializers.CharField()
    href = serializers.CharField()


class OperationalQueueSerializer(serializers.Serializer):
    name = serializers.CharField()
    queued = serializers.IntegerField()
    running = serializers.IntegerField()
    failed = serializers.IntegerField()
    worker_status = serializers.ChoiceField(choices=["unknown"])


class OperationalHealthSerializer(serializers.Serializer):
    checked_at = serializers.DateTimeField()
    production_readiness = serializers.ChoiceField(choices=["incomplete"])
    components = OperationalCheckSerializer(many=True)
    integrations = OperationalCheckSerializer(many=True)
    queues = OperationalQueueSerializer(many=True)
    checklist = OperationalCheckSerializer(many=True)
