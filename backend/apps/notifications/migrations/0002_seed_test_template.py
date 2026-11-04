"""Seed the SMTP test message template (Task 018a). Event templates arrive with the alert
rules (Task 018b)."""

from django.db import migrations

TEMPLATE = {
    "code": "smtp_test",
    "name": "SMTP test message",
    "description": "Sent by 'Send test email' to the administrator who asked for it.",
    "variables": [
        {
            "name": "requested_by",
            "description": "Name of the administrator who sent the test",
            "example": "Admin One",
        },
        {"name": "app_url", "description": "Link to ITAM", "example": "https://itam.example.org"},
    ],
    "subject": "{{ app_name }} test message",
    "body_text": (
        "Hello {{ requested_by }},\n\n"
        "This is a test message from {{ app_name }}. Mail delivery works with the current SMTP "
        "settings.\n\n"
        "{% if app_url %}{{ app_url }}\n{% endif %}"
        "Sent {{ now|date:'Y-m-d H:i' }} UTC. No action is needed.\n"
    ),
    "body_html": (
        "<p>Hello {{ requested_by }},</p>\n"
        "<p>This is a test message from {{ app_name }}. Mail delivery works with the current "
        "SMTP settings.</p>\n"
        '{% if app_url %}<p><a href="{{ app_url }}">{{ app_url }}</a></p>{% endif %}\n'
        "<p>Sent {{ now|date:'Y-m-d H:i' }} UTC. No action is needed.</p>\n"
    ),
}


def forwards(apps, schema_editor):
    Template = apps.get_model("notifications", "NotificationTemplate")
    code = TEMPLATE["code"]
    Template.objects.get_or_create(
        code=code, defaults={k: v for k, v in TEMPLATE.items() if k != "code"}
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        code=TEMPLATE["code"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_smtp_templates_outbox")]

    operations = [migrations.RunPython(forwards, backwards)]
