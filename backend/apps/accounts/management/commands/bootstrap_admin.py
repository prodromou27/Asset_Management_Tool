"""Create a named System Admin from a protected shell.

The password is read interactively (or from stdin with --password-stdin);
it is never accepted as a command-line argument or environment variable.
"""

import getpass
import sys

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.catalog import SYSTEM_ADMIN
from apps.accounts.models import USERNAME_VALIDATOR, Role, User
from apps.accounts.services import snapshot
from apps.audit import services as audit
from apps.audit.models import AuditEvent


class Command(BaseCommand):
    help = "Create a named System Admin account (first-run and emergency admins)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--display-name", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help="Read the password from the first line of stdin instead of prompting.",
        )

    def handle(self, *args, username, display_name, email, password_stdin, **options):
        username = username.strip().lower()
        email = email.strip().lower()
        try:
            USERNAME_VALIDATOR(username)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists.")
        if email and User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"Email '{email}' is already in use.")

        password = self._read_password(password_stdin)
        probe = User(username=username, email=email, display_name=display_name)
        try:
            validate_password(password, probe)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        role = Role.objects.get(code=SYSTEM_ADMIN)
        operator = _os_user()
        with transaction.atomic():
            user = User.objects.create_user(
                username, password, email=email, display_name=display_name
            )
            user.roles.add(role)
            audit.record(
                action="users.bootstrap_admin",
                actor_label=f"cli:{operator}",
                object_type="user",
                object_id=user.pk,
                object_label=user.username,
                after=snapshot(user),
                source=AuditEvent.Source.CLI,
                detail=f"Created by bootstrap_admin at {timezone.now().isoformat()}",
            )
        self.stdout.write(self.style.SUCCESS(f"System Admin '{username}' created."))

    def _read_password(self, from_stdin: bool) -> str:
        if from_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
            if not password:
                raise CommandError("No password received on stdin.")
            return password
        if not sys.stdin.isatty():
            raise CommandError("No TTY: run interactively or use --password-stdin.")
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Password (again): ")
        if first != second:
            raise CommandError("Passwords do not match.")
        return first


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - containers may lack a passwd entry
        return "unknown"
