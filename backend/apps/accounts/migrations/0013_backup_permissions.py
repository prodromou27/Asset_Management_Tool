from django.db import migrations


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    for code, description in {
        "backups.view": "View backup operations and recovery reports (never backup files or secrets)",
        "backups.manage": "Configure backup policy, request backups and verification, record restore drills",
    }.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    for role_code, codes in {
        "system_admin": ["backups.view", "backups.manage"],
        "auditor": ["backups.view"],
    }.items():
        role = Role.objects.filter(code=role_code).first()
        if role:
            role.permissions.add(*Permission.objects.filter(code__in=codes))


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(
        code__in=["backups.view", "backups.manage"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_notification_permissions")]
    operations = [migrations.RunPython(forwards, backwards)]
