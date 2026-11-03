"""Defender for Endpoint adapter implemented and contract-tested on sanitized fixtures: Beta.

It becomes Available only after validation against the organization's tenant (DEC-16:
app registration with the WindowsDefenderATP application permission Machine.Read.All).
"""

from django.db import migrations

ORIGINAL_DESCRIPTION = "Machines API, read-only."


def forwards(apps, schema_editor):
    source = apps.get_model("integrations", "DiscoverySource").objects.filter(code="defender")
    source.update(
        availability="beta",
        description="Defender for Endpoint API machines (GET only), application permission "
        "Machine.Read.All. Security facts kept apart from asset fields.",
    )


def backwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="defender").update(
        availability="planned", description=ORIGINAL_DESCRIPTION
    )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0008_intune_beta")]

    operations = [migrations.RunPython(forwards, backwards)]
