"""Task 013: permission to run CSV/XLSX imports (docs/09: admin, ITAM manager, operator)."""

from django.db import migrations

NEW_PERMISSIONS = {
    "imports.run": "Upload, preview and commit CSV/XLSX imports (plus the family's own permission)",
}

GRANTS = {
    "system_admin": ["imports.run"],
    "itam_manager": ["imports.run"],
    "asset_operator": ["imports.run"],
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
    dependencies = [("accounts", "0006_group_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
