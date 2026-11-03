"""Microsoft 365 / Entra license adapter implemented and contract-tested on sanitized
Graph fixtures: Beta.

It becomes Available only after validation against the organization's tenant (DEC-17:
app registration with Organization.Read.All and User.Read.All, admin consent).
"""

from django.db import migrations

ORIGINAL_DESCRIPTION = "SKUs and assignments (licensing task)."


def forwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="m365").update(
        availability="beta",
        description="Microsoft Graph v1.0 subscribedSkus and user license assignments (GET "
        "only). Tenant inventory, not billing or license compliance.",
    )


def backwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="m365").update(
        availability="planned", description=ORIGINAL_DESCRIPTION
    )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0009_defender_beta")]

    operations = [migrations.RunPython(forwards, backwards)]
