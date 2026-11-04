"""Seed the alert templates used by notification rules (Task 018b). Administrators can edit
them; every message records the template version it was rendered with."""

from django.db import migrations

ITEM_VARIABLES = [
    {"name": "rule_name", "description": "Name of the rule", "example": "Certificate owners"},
    {"name": "count", "description": "Number of new items", "example": "2"},
    {"name": "more", "description": "Items left for the next message", "example": "0"},
    {
        "name": "items",
        "description": "List with title, detail, date, status and url per item",
        "example": "",
    },
]

TEXT_LIST = (
    "{% for item in items %}- {{ item.title }}: {{ item.status }} ({{ item.date }})\n"
    "  {{ item.detail }}\n  {{ item.url }}\n{% endfor %}"
    "{% if more %}\n{{ more }} more item{{ more|pluralize }} will follow in the next message.\n"
    "{% endif %}"
)
HTML_LIST = (
    '<ul>{% for item in items %}<li><a href="{{ item.url }}">{{ item.title }}</a>: '
    "<strong>{{ item.status }}</strong> ({{ item.date }})<br>{{ item.detail }}</li>"
    "{% endfor %}</ul>"
    "{% if more %}<p>{{ more }} more item{{ more|pluralize }} will follow in the next "
    "message.</p>{% endif %}"
)
FOOTER_TEXT = '\nYou receive this because of the ITAM notification rule "{{ rule_name }}".\n'
FOOTER_HTML = (
    '<p style="color:#555">You receive this because of the ITAM notification rule '
    "&quot;{{ rule_name }}&quot;.</p>"
)


def template(code, name, description, subject, intro):
    return {
        "code": code,
        "name": name,
        "description": description,
        "variables": ITEM_VARIABLES,
        "subject": subject,
        "body_text": f"{intro}\n\n{TEXT_LIST}{FOOTER_TEXT}",
        "body_html": f"<p>{intro}</p>\n{HTML_LIST}\n{FOOTER_HTML}",
    }


TEMPLATES = [
    template(
        "certificate_expiry",
        "TLS certificate expiry",
        "Certificates presented by approved endpoints, or uploaded, reaching a threshold.",
        "{{ app_name }}: {{ count }} certificate{{ count|pluralize }} expiring or expired",
        "These TLS certificates reached an expiry threshold:",
    ),
    template(
        "domain_expiry",
        "Domain registration expiry",
        "Domains with a recorded (evidenced) registration expiry reaching a threshold.",
        "{{ app_name }}: {{ count }} domain{{ count|pluralize }} due for renewal",
        "These domain registrations reached an expiry threshold:",
    ),
    template(
        "lifecycle_eol",
        "Verified end of life / support",
        "Assets whose verified lifecycle milestone reaches a threshold. Unverified dates are "
        "never announced.",
        "{{ app_name }}: {{ count }} asset lifecycle milestone{{ count|pluralize }}",
        "These assets reached a verified lifecycle milestone threshold:",
    ),
    template(
        "integration_failure",
        "Integration failures and stale syncs",
        "Integrations whose last runs failed or whose data is older than the stale limit.",
        "{{ app_name }}: {{ count }} integration problem{{ count|pluralize }}",
        "These integrations need attention:",
    ),
]


def forwards(apps, schema_editor):
    Template = apps.get_model("notifications", "NotificationTemplate")
    for item in TEMPLATES:
        Template.objects.get_or_create(
            code=item["code"], defaults={k: v for k, v in item.items() if k != "code"}
        )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        code__in=[t["code"] for t in TEMPLATES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_notification_rules")]

    operations = [migrations.RunPython(forwards, backwards)]
