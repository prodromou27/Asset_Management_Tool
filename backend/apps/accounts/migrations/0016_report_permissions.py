from django.db import migrations


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    for code, description in {
        "reports.view": "View reports within current site and field permissions",
        "reports.schedule": "Schedule authenticated report links to your own account",
    }.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    for role in Role.objects.all():
        if role.permissions.filter(code="assets.view").exists():
            role.permissions.add(Permission.objects.get(code="reports.view"))
        if role.code in ("system_admin", "itam_manager"):
            role.permissions.add(Permission.objects.get(code="reports.schedule"))


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(
        code__in=["reports.view", "reports.schedule"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_admin_permissions")]
    operations = [migrations.RunPython(forwards, backwards)]
