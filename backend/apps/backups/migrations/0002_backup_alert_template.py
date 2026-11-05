from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.get_or_create(
        code="backup_alert",
        defaults={
            "name": "Backup operations",
            "description": "Backup failure, failed restore drill or recovery point overdue",
            "variables": [{"name": "message", "description": "Redacted operational finding"}],
            "subject": "ITAM backup requires attention",
            "body_text": "{{ message }}\n{{ app_url }}/admin/backups",
            "body_html": "<p>{{ message }}</p>",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        code="backup_alert"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("backups", "0001_initial"), ("notifications", "0004_seed_alert_templates")]
    operations = [migrations.RunPython(forwards, backwards)]
