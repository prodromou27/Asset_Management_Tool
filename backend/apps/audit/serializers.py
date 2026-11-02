from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "occurred_at",
            "actor_id",
            "actor_label",
            "action",
            "object_type",
            "object_id",
            "object_label",
            "outcome",
            "source",
            "before",
            "after",
            "detail",
            "request_id",
            "ip_address",
        ]
        read_only_fields = fields
