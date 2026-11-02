"""Seed the default category taxonomy (docs/01). Admins may edit it afterwards.

Software, licences, domains and certificates are separate modules (later tasks),
not asset categories.
"""

from django.db import migrations

TAXONOMY = [
    ("workstations", "Workstations", ["Desktop", "Laptop", "Thin Client"]),
    ("servers", "Servers", ["Physical Server", "Virtual Machine", "Hypervisor"]),
    (
        "networking",
        "Networking",
        ["Switch", "Router", "Access Point", "Wireless Controller", "Load Balancer"],
    ),
    ("security", "Security", ["Firewall", "VPN Gateway", "Web Application Firewall"]),
    ("printers", "Printers", ["Printer", "Scanner", "Multifunction Printer"]),
    ("monitors", "Monitors", []),
    ("ip-phones", "IP Phones", []),
    ("tvs", "TVs", ["Conference Display"]),
    ("ups", "UPS", []),
    ("power", "Power Distribution", ["PDU"]),
    ("storage", "Storage", ["Storage Array", "NAS", "Backup Appliance"]),
    ("peripherals", "Peripherals", ["Docking Station"]),
    ("other", "Other", ["Unknown"]),
]


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def seed(apps, schema_editor):
    Category = apps.get_model("assets", "AssetCategory")
    for order, (code, name, children) in enumerate(TAXONOMY):
        parent, _ = Category.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": order * 10}
        )
        for child_order, child in enumerate(children):
            Category.objects.get_or_create(
                code=f"{code}-{_slug(child)}",
                defaults={"name": child, "parent": parent, "sort_order": child_order * 10},
            )


def unseed(apps, schema_editor):
    Category = apps.get_model("assets", "AssetCategory")
    codes = [code for code, _, _ in TAXONOMY]
    Category.objects.filter(parent__code__in=codes, assets__isnull=True).delete()
    Category.objects.filter(code__in=codes, assets__isnull=True, children__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("assets", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
