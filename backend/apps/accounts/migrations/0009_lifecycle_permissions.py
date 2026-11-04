"""Task 015: lifecycle permissions (docs/09: ITAM Manager approves/excepts, Infrastructure
Engineer proposes, everyone with asset read access may read lifecycle evidence).

``lifecycle.manage`` enters products, aliases, sources and dates, which stay unverified;
``lifecycle.approve`` verifies evidence, approves or rejects matches and grants exceptions.
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "lifecycle.view": "View lifecycle catalogue, evidence and asset lifecycle assessments",
    "lifecycle.manage": "Add and edit lifecycle products, aliases, sources and dates (unverified)",
    "lifecycle.approve": "Verify lifecycle evidence, approve or reject matches and grant exceptions",
}

GRANTS = {
    "system_admin": ["lifecycle.view", "lifecycle.manage", "lifecycle.approve"],
    "itam_manager": ["lifecycle.view", "lifecycle.manage", "lifecycle.approve"],
    "infrastructure_engineer": ["lifecycle.view", "lifecycle.manage"],
    "security_analyst": ["lifecycle.view"],
    "asset_operator": ["lifecycle.view"],
    "auditor": ["lifecycle.view"],
    "read_only": ["lifecycle.view"],
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
    dependencies = [("accounts", "0008_export_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
