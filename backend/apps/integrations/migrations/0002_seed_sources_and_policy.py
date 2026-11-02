"""Seed the source catalogue and default field authority.

Vendor sources are `planned`: no adapter exists yet (docs/15 A21). The `fixture`
source loads sanitized JSON via `manage.py load_observations` for pilots/tests.
"""

from django.db import migrations

SOURCES = [
    (
        "librenms",
        "LibreNMS",
        "network",
        "planned",
        "Read-only REST: devices, ports, IPs, FDB, inventory.",
    ),
    (
        "endpoint_central",
        "Endpoint Central (on-premises)",
        "endpoint",
        "planned",
        "Read-only inventory API.",
    ),
    ("intune", "Microsoft Intune", "endpoint", "planned", "Graph managedDevices, read-only."),
    (
        "defender",
        "Microsoft Defender for Endpoint",
        "security",
        "planned",
        "Machines API, read-only.",
    ),
    (
        "m365",
        "Microsoft 365 / Entra",
        "directory",
        "planned",
        "SKUs and assignments (licensing task).",
    ),
    (
        "fixture",
        "Sanitized fixture import",
        "import",
        "available",
        "Loads sanitized JSON source records with manage.py load_observations. No network access.",
    ),
]

# Earlier sources in each list win when sources disagree. Manual locks beat all.
PRECEDENCE = {
    "manufacturer": ["endpoint_central", "intune", "librenms", "defender", "fixture"],
    "model": ["endpoint_central", "intune", "librenms", "defender", "fixture"],
    "serial_number": ["endpoint_central", "intune", "librenms", "defender", "fixture"],
    "os_name": ["endpoint_central", "intune", "defender", "librenms", "fixture"],
    "os_version": ["endpoint_central", "intune", "defender", "librenms", "fixture"],
    "firmware_version": ["librenms", "endpoint_central", "intune", "defender", "fixture"],
}


def seed(apps, schema_editor):
    Source = apps.get_model("integrations", "DiscoverySource")
    Policy = apps.get_model("integrations", "FieldAuthorityPolicy")
    for code, name, kind, availability, description in SOURCES:
        Source.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "kind": kind,
                "availability": availability,
                "description": description,
            },
        )
    Policy.objects.update_or_create(pk=1, defaults={"precedence": PRECEDENCE})


def unseed(apps, schema_editor):
    apps.get_model("integrations", "FieldAuthorityPolicy").objects.filter(pk=1).delete()
    apps.get_model("integrations", "DiscoverySource").objects.filter(
        code__in=[s[0] for s in SOURCES], instances__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
