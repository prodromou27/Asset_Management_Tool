"""LibreNMS adapter implemented and contract-tested on sanitized fixtures: Beta.

It becomes Available only after validation against the organization's installed
LibreNMS (Docker-host verification and an approved read-only API account).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="librenms").update(
        availability="beta",
        description="Read-only API v0 (GET only): devices, IPs, ports, inventory, FDB and neighbour links.",
    )


def backwards(apps, schema_editor):
    apps.get_model("integrations", "DiscoverySource").objects.filter(code="librenms").update(
        availability="planned"
    )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_integrationinstance_auth_scheme_and_more")]

    operations = [migrations.RunPython(forwards, backwards)]
