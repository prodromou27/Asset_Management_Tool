"""Audited, one-use, 15-minute local recovery from the protected operator shell."""

from django.core.management.base import CommandError
from rest_framework.exceptions import ValidationError

from apps.accounts.entra_admin import open_emergency_access

from .bootstrap_admin import Command as BootstrapCommand
from .bootstrap_admin import _os_user


class Command(BootstrapCommand):
    help = "Open one-use emergency access for a named admin; rotates password and revokes sessions."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument(
            "--reason", required=True, help="Incident/change reference; never credentials"
        )
        parser.add_argument("--password-stdin", action="store_true")

    def handle(self, *args, username, reason, password_stdin, **options):
        if not reason.strip() or len(reason) > 500:
            raise CommandError(
                "Supply a nonempty incident/change reference, at most 500 characters."
            )
        password = self._read_password(password_stdin)
        try:
            user = open_emergency_access(
                username.strip().lower(), password, reason.strip(), _os_user()
            )
        except (ValueError, ValidationError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            f"Emergency access opened for {user.username} until "
            f"{user.emergency_access_until.isoformat()}. One sign-in only."
        )
