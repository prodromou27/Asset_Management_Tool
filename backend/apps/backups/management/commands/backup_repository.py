"""Explicit operator-only repository setup/check with the same pinned transport as jobs."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.audit import services as audit
from apps.backups import runner, services
from config.api import ApiError


class Command(BaseCommand):
    help = "Initialize or integrity-check the deployment-provisioned backup repository."

    def add_arguments(self, parser):
        parser.add_argument("operation", choices=["init", "check"])

    def handle(self, *args, **options):
        try:
            services.gate()
            command = [options["operation"]]
            if command == ["check"]:
                command.append("--read-data")
            runner.restic(command, env=runner.repository_env())
        except runner.RunnerError as exc:
            raise CommandError(str(exc)) from None
        except ApiError:
            raise CommandError(
                "Backup execution is disabled by deployment configuration."
            ) from None
        audit.record(
            action=f"backups.repository_{options['operation']}",
            actor_label="backup-operator",
            source="cli",
            object_type="backup_repository",
            object_label=settings.ITAM_BACKUP_TARGET_LABEL,
        )
        self.stdout.write(
            self.style.SUCCESS("Repository operation completed; no credentials displayed.")
        )
