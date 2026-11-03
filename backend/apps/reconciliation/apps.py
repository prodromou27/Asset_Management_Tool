from django.apps import AppConfig


class ReconciliationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reconciliation"
    label = "reconciliation"

    def ready(self):
        from apps.assets.signals import asset_reclassified

        from .category_review import on_reclassified

        asset_reclassified.connect(on_reclassified, dispatch_uid="reconciliation.category_review")
