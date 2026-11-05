from django.db import migrations


def forwards(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    codes = {
        "settings.general.view": "View organization display settings",
        "settings.general.manage": "Change organization display settings",
        "health.view": "View operational diagnostics and production readiness (no secrets)",
    }
    for code, description in codes.items():
        Permission.objects.update_or_create(code=code, defaults={"description": description})
    grants = {
        "system_admin": list(codes),
        "auditor": ["settings.general.view", "health.view"],
        "itam_manager": ["health.view"],
        "infrastructure_engineer": ["health.view"],
        "security_analyst": ["health.view"],
    }
    for role_code, permissions in grants.items():
        role = Role.objects.filter(code=role_code).first()
        if role:
            role.permissions.add(*Permission.objects.filter(code__in=permissions))


def backwards(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(
        code__in=["settings.general.view", "settings.general.manage", "health.view"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_generalsettings")]
    operations = [migrations.RunPython(forwards, backwards)]
