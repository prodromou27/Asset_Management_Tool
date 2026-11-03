"""Task 010: permission to view license subscriptions and user license assignments."""

from django.db import migrations

NEW_PERMISSIONS = {
    "licenses.view": "View license subscriptions, quantities and user license assignments",
}

GRANTS = {
    "system_admin": ["licenses.view"],
    "itam_manager": ["licenses.view"],
    "auditor": ["licenses.view"],
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
    dependencies = [("accounts", "0004_discovery_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
