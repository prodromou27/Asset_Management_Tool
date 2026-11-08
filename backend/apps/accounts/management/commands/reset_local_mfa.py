"""Local-factor recovery is restricted to the protected operator shell."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditEvent

from .bootstrap_admin import _os_user


class Command(BaseCommand):
    help = "Reset a lost local authenticator after verified identity recovery; revokes sessions."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, username, reason, **options):
        if not reason.strip() or len(reason) > 500:
            raise CommandError("Supply an incident reference, at most 500 characters.")
        with transaction.atomic():
            user = (
                User.objects.select_for_update().filter(username=username.strip().lower()).first()
            )
            if not user:
                raise CommandError("Named account not found.")
            user.mfa_secret = user.mfa_pending_secret = b""
            user.mfa_pending_until = user.emergency_access_until = None
            user.mfa_recovery_hashes = []
            user.mfa_last_step = -1
            user.session_epoch = F("session_epoch") + 1
            user.version = F("version") + 1
            user.save()
            audit.record(
                action="auth.mfa_operator_reset",
                actor_label=f"cli:{_os_user()}",
                source=AuditEvent.Source.CLI,
                object_type="user",
                object_id=user.pk,
                object_label=user.username,
                detail=reason.strip(),
            )
        self.stdout.write(
            "Local MFA reset; existing sessions revoked. Sign-in permissions unchanged."
        )
