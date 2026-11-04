"""Task 014: export permissions (docs/09 role matrix, docs/14 personal-data export).

``exports.run``: every role may export what it can already see (docs/09: from "Limited
filtered export" for Read Only to full export for admins); the data is always the user's
own site-scoped view. ``exports.personal``: people's names and usernames in exports, kept
separate from technical inventory export (docs/14) - System Admin, ITAM Manager and Asset
Operator (ASM-52).
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "exports.run": "Export data you can view (site-scoped) to CSV, XLSX or JSON",
    "exports.personal": "Include personal data (owner and user names) in exports",
}

GRANTS = {
    "system_admin": ["exports.run", "exports.personal"],
    "itam_manager": ["exports.run", "exports.personal"],
    "asset_operator": ["exports.run", "exports.personal"],
    "infrastructure_engineer": ["exports.run"],
    "security_analyst": ["exports.run"],
    "auditor": ["exports.run"],
    "read_only": ["exports.run"],
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
    dependencies = [("accounts", "0007_import_permission")]

    operations = [migrations.RunPython(forwards, backwards)]
