"""Task 018a: SMTP and notification permissions.

docs/10: changing mail configuration needs an administrator; the Auditor may read the
settings (never credentials) and the delivery queue.
"""

from django.db import migrations

NEW_PERMISSIONS = {
    "notifications.view": "View SMTP settings (without credentials), templates and the mail queue",
    "notifications.manage": (
        "Change SMTP settings and templates, test mail and retry or cancel queued messages"
    ),
}

GRANTS = {
    "system_admin": ["notifications.view", "notifications.manage"],
    "auditor": ["notifications.view"],
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
    dependencies = [("accounts", "0011_certificate_permissions")]

    operations = [migrations.RunPython(forwards, backwards)]
