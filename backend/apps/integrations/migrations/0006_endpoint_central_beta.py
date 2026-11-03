"""Endpoint Central adapter implemented and contract-tested on sanitized fixtures: Beta.

It becomes Available only after validation against the organization's installed
Endpoint Central build (Docker-host verification and an approved read-only API key).
"""

from django.db import migrations

ORIGINAL = "Read-only inventory API."


def forwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(
        code="endpoint_central"
    ).update(
        availability="beta",
        description="Read-only inventory API (GET only): computers, hardware, OS and network "
        "adapters. dcapi or api/1.4, detected per installation.",
    )


def backwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(
        code="endpoint_central"
    ).update(availability="planned", description=ORIGINAL)


class Migration(migrations.Migration):
    dependencies = [("integrations", "0005_authorization_scheme")]

    operations = [migrations.RunPython(forwards, backwards)]
