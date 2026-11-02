"""Load sanitized source records from a JSON file into one integration instance.

Operator-run (protected shell). Used for fixtures, pilots and adapter development
until real connectors exist. It never contacts any network or source system.

    python manage.py load_observations --instance "Fixture LibreNMS" \\
        --file fixtures/discovery/librenms_switches.json --mode full
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import IntegrationInstance, SyncRun
from apps.reconciliation import services

MAX_BYTES = 20 * 1024 * 1024


class Command(BaseCommand):
    help = "Ingest a JSON array of source records (see fixtures/discovery/README.md)."

    def add_arguments(self, parser):
        parser.add_argument("--instance", required=True, help="Integration instance name")
        parser.add_argument("--file", required=True)
        parser.add_argument("--mode", choices=SyncRun.Mode.values, default=SyncRun.Mode.INCREMENTAL)

    def handle(self, *args, instance, file, mode, **options):
        target = IntegrationInstance.objects.filter(name=instance).select_related("source").first()
        if target is None:
            raise CommandError(f"No integration instance named {instance!r}.")
        if not target.is_enabled:
            raise CommandError("The integration instance is disabled.")
        path = Path(file)
        if not path.is_file():
            raise CommandError(f"File not found: {file}")
        if path.stat().st_size > MAX_BYTES:
            raise CommandError("File is larger than 20 MB; split it into batches.")
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc
        if not isinstance(records, list):
            raise CommandError("The file must contain a JSON array of records.")

        run = services.ingest(target, records, mode=mode, triggered_by="cli:load_observations")
        self.stdout.write(
            f"Run {run.id}: {run.status}. received={run.records_received} "
            f"new_observations={run.observations_created} "
            f"unchanged={run.observations_unchanged} "
            f"links_refreshed={run.links_refreshed} stale={run.links_marked_stale} "
            f"candidates_opened={run.candidates_opened} "
            f"candidates_updated={run.candidates_updated} "
            f"assets_updated={run.assets_updated} conflicts={run.conflicts_opened} "
            f"errors={run.errors}"
        )
