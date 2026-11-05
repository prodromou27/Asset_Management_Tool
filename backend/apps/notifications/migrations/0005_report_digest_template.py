from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.get_or_create(
        code="report_digest",
        defaults={
            "name": "Scheduled report link",
            "subject": "ITAM scheduled report",
            "body_text": "Your scheduled {{ report_label }} is ready to review.\n"
            "Sign in to view current authorized data: {{ report_url }}\n"
            "No inventory data or attachment is included in this email.",
            "body_html": "",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        code="report_digest"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_seed_alert_templates")]
    operations = [migrations.RunPython(forwards, backwards)]
