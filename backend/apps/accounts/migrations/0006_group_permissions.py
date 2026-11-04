"""Task 012: asset group permissions (docs/09 role matrix)."""

from django.db import migrations

NEW_PERMISSIONS = {
    "groups.view": "View asset groups and their members in permitted sites",
    "groups.manage": "Create, edit and archive asset groups and dynamic group rules",
    "groups.members": "Add and remove static group members in permitted sites",
}

GRANTS = {
    "system_admin": list(NEW_PERMISSIONS),
    "itam_manager": list(NEW_PERMISSIONS),
    "infrastructure_engineer": ["groups.view", "groups.members"],
    "security_analyst": ["groups.view"],
    "asset_operator": ["groups.view", "groups.members"],
    "auditor": ["groups.view"],
    "read_only": ["groups.view"],
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
    dependencies = [("accounts", "0005_license_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
