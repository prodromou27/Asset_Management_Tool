"""Microsoft Intune adapter implemented and contract-tested on sanitized Graph fixtures: Beta.

It becomes Available only after validation against the organization's tenant (DEC-07:
app registration with DeviceManagementManagedDevices.Read.All and admin consent).
"""

from django.db import migrations

ORIGINAL = "Graph managedDevices, read-only."


def forwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="intune").update(
        availability="beta",
        description="Microsoft Graph v1.0 managedDevices (GET only), application permission "
        "DeviceManagementManagedDevices.Read.All.",
    )


def backwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="intune").update(
        availability="planned", description=ORIGINAL
    )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0007_intune_oauth_settings")]

    operations = [migrations.RunPython(forwards, backwards)]
