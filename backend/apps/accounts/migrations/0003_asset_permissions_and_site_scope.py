"""Task 003: site scope flag on users and asset/category/site permissions.

Existing System Admins get all_sites=True so current admins keep full access.
Values are inlined so the migration stays reproducible.
"""

from django.db import migrations, models

NEW_PERMISSIONS = {
    "assets.view": "View assets in permitted sites",
    "assets.create": "Register assets in permitted sites",
    "assets.edit": "Edit and reassign assets in permitted sites",
    "assets.reclassify": "Change an asset's category",
    "assets.archive": "Archive and restore assets",
    "categories.manage": "Manage asset categories and custom field definitions",
    "sites.manage": "Manage sites, locations and departments",
}

GRANTS = {
    "system_admin": list(NEW_PERMISSIONS),
    "itam_manager": [
        "assets.view",
        "assets.create",
        "assets.edit",
        "assets.reclassify",
        "assets.archive",
    ],
    "infrastructure_engineer": ["assets.view"],
    "security_analyst": ["assets.view"],
    "asset_operator": ["assets.view", "assets.create", "assets.edit"],
    "auditor": ["assets.view"],
    "read_only": ["assets.view"],
}


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    User = apps.get_model("accounts", "User")

    for code, description in NEW_PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    for role_code, perms in GRANTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is not None:
            role.permissions.add(*Permission.objects.filter(code__in=perms))
    User.objects.filter(roles__code="system_admin").update(all_sites=True)


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code__in=NEW_PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_seed_roles_permissions")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="all_sites",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(forwards, backwards),
    ]
