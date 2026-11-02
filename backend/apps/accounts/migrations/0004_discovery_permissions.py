"""Task 004: discovery/reconciliation permissions and technical-field authority (ASM-09)."""

from django.db import migrations

NEW_PERMISSIONS = {
    "assets.edit_technical": "Edit discovered technical fields, lock/unlock fields, resolve field conflicts",
    "assets.merge": "Merge duplicate assets and revert merges",
    "discovery.view": "View discovery sources, observations, candidates and source evidence",
    "reconciliation.decide": "Approve, reject or hold reconciliation candidates; unlink sources",
    "integrations.manage": "Configure integration instances and field authority",
}

GRANTS = {
    "system_admin": list(NEW_PERMISSIONS),
    "itam_manager": [
        "assets.edit_technical",
        "assets.merge",
        "discovery.view",
        "reconciliation.decide",
    ],
    "infrastructure_engineer": ["assets.edit_technical", "discovery.view"],
    "security_analyst": ["discovery.view"],
    "auditor": ["discovery.view"],
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
    dependencies = [("accounts", "0003_asset_permissions_and_site_scope")]

    operations = [migrations.RunPython(forwards, backwards)]
