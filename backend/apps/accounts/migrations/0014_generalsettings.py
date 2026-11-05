import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_backup_permissions")]
    operations = [
        migrations.CreateModel(
            name="GeneralSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("organization_name", models.CharField(default="ITAM", max_length=100)),
                ("timezone", models.CharField(default="Asia/Nicosia", max_length=64)),
                (
                    "date_format",
                    models.CharField(
                        choices=[
                            ("day_month_year", "Day month year"),
                            ("month_day_year", "Month day year"),
                            ("iso", "ISO 8601"),
                        ],
                        default="day_month_year",
                        max_length=20,
                    ),
                ),
                (
                    "language",
                    models.CharField(choices=[("en", "English")], default="en", max_length=5),
                ),
                ("support_contact", models.EmailField(blank=True, max_length=254)),
                ("version", models.PositiveIntegerField(default=1)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1), name="general_settings_singleton"
                    )
                ]
            },
        ),
    ]
