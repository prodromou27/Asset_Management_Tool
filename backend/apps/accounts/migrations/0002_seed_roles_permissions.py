"""Seed the documented roles (docs/09) and Task 002 permissions.

Values are inlined (not imported from catalog.py) so this migration stays
reproducible after the catalogue evolves. Later tasks add permissions in
their own migrations.
"""

from django.db import migrations

PERMISSIONS = {
    "users.view": "View user accounts, role assignments and access review data",
    "users.manage": "Create, edit, disable and enable user accounts and their roles",
    "roles.view": "View roles and the permissions each role grants",
    "audit.view": "View the audit log",
    "settings.security.view": "View session, lockout and password policy settings",
    "settings.security.manage": "Change session, lockout and password policy settings",
}

ROLES = [
    (
        "system_admin",
        "System Admin",
        "Full administration of users, settings, integrations and backups.",
        list(PERMISSIONS),
    ),
    (
        "itam_manager",
        "ITAM Manager",
        "Curates asset data, approves lifecycle matches and exceptions.",
        [],
    ),
    (
        "infrastructure_engineer",
        "Infrastructure Engineer",
        "Technical comments, match proposals and source diagnostics.",
        [],
    ),
    (
        "security_analyst",
        "Security Analyst",
        "Read and investigate assets; flag high-risk lifecycle findings.",
        [],
    ),
    (
        "asset_operator",
        "Asset Operator",
        "Maintains authorized business fields and static group membership.",
        [],
    ),
    (
        "auditor",
        "Auditor",
        "Read-only access to evidence, health and the audit log.",
        ["users.view", "roles.view", "audit.view", "settings.security.view"],
    ),
    ("read_only", "Read Only", "Site-scoped read access.", []),
]


def seed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    SecuritySettings = apps.get_model("accounts", "SecuritySettings")

    for code, description in PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    for code, name, description, perms in ROLES:
        role, _ = Role.objects.update_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True}
        )
        role.permissions.add(*Permission.objects.filter(code__in=perms))
    SecuritySettings.objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    apps.get_model("accounts", "Role").objects.filter(code__in=[r[0] for r in ROLES]).delete()
    apps.get_model("accounts", "Permission").objects.filter(code__in=PERMISSIONS).delete()
    apps.get_model("accounts", "SecuritySettings").objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
