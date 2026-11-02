from rest_framework import serializers

from .models import SITE_CODE_VALIDATOR, Department, Location, Site


class SiteSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "code", "name"]
        read_only_fields = fields


class SiteSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)

    class Meta:
        model = Site
        fields = [
            "id",
            "code",
            "name",
            "parent",
            "description",
            "is_active",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields


class SiteWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=150)
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.all(), allow_null=True, required=False
    )
    description = serializers.CharField(max_length=500, allow_blank=True, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value):
        value = value.strip().upper()
        SITE_CODE_VALIDATOR(value)
        existing = Site.objects.filter(code=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError("This site code is already in use.")
        return value


class LocationSerializer(serializers.ModelSerializer):
    site = serializers.PrimaryKeyRelatedField(read_only=True)
    parent = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)

    class Meta:
        model = Location
        fields = [
            "id",
            "site",
            "parent",
            "name",
            "kind",
            "is_active",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields


class LocationWriteSerializer(serializers.Serializer):
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), allow_null=True, required=False
    )
    name = serializers.CharField(max_length=150)
    kind = serializers.ChoiceField(choices=Location.Kind.choices, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        name = attrs.get("name", getattr(self.instance, "name", ""))
        parent = attrs["parent"] if "parent" in attrs else getattr(self.instance, "parent", None)
        clash = Location.objects.filter(site=site, parent=parent, name__iexact=name.strip())
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {"name": ["A location with this name already exists here."]}
            )
        return attrs


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "code", "is_active", "created_at", "modified_at", "version"]
        read_only_fields = fields


class DepartmentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    code = serializers.CharField(max_length=32, allow_blank=True, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value):
        value = value.strip()
        clash = Department.objects.filter(name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A department with this name already exists.")
        return value
