"""Task 016b: permission to maintain license products, entitlements and allocations.

Granted to System Admin and ITAM Manager (docs/09: the ITAM Manager curates asset and
license data). Viewing keeps using ``licenses.view``.
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "licenses.manage": "Maintain license products, entitlements and allocations",
}

GRANTS = {
    "system_admin": ["licenses.manage"],
    "itam_manager": ["licenses.manage"],
}


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    for code, description in NEW_PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    for role_code, perms in GRANTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is not None:
            role.permissions.add(*Permission.objects.filter(code__in=perms))


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code__in=NEW_PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_lifecycle_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
