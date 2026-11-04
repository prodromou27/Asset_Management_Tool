"""Task 017: domain and certificate permissions.

Everyone with asset read access may view domains, certificates and endpoints;
System Admin, ITAM Manager and Infrastructure Engineer maintain them and approve the TLS
endpoints ITAM may contact.
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "certificates.view": "View domains, TLS certificates and approved TLS endpoints",
    "certificates.manage": (
        "Maintain domains, upload certificates and approve, check or retire TLS endpoints"
    ),
}

GRANTS = {
    "system_admin": ["certificates.view", "certificates.manage"],
    "itam_manager": ["certificates.view", "certificates.manage"],
    "infrastructure_engineer": ["certificates.view", "certificates.manage"],
    "security_analyst": ["certificates.view"],
    "asset_operator": ["certificates.view"],
    "auditor": ["certificates.view"],
    "read_only": ["certificates.view"],
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
    dependencies = [("accounts", "0010_license_manage_permission")]

    operations = [migrations.RunPython(forwards, backwards)]
