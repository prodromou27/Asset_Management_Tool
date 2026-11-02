import io

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

STRONG = "Bootstrap-Strong-Pass-1"


def run(monkeypatch, stdin_text, *args):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    out = io.StringIO()
    call_command("bootstrap_admin", *args, stdout=out)
    return out.getvalue()


def test_creates_named_system_admin_from_stdin(monkeypatch):
    output = run(
        monkeypatch,
        STRONG + "\n",
        "--username=Ops.Admin",
        "--display-name=Ops Admin",
        "--email=ops@example.test",
        "--password-stdin",
    )

    user = User.objects.get(username="ops.admin")
    assert "created" in output and STRONG not in output
    assert user.check_password(STRONG)
    assert user.must_change_password is False
    assert list(user.roles.values_list("code", flat=True)) == ["system_admin"]
    event = AuditEvent.objects.get(action="users.bootstrap_admin")
    assert event.source == "cli" and event.actor_label.startswith("cli:")


def test_second_emergency_admin_can_be_created(monkeypatch):
    run(monkeypatch, STRONG + "\n", "--username=admin.a", "--display-name=A", "--password-stdin")
    run(monkeypatch, STRONG + "\n", "--username=admin.b", "--display-name=B", "--password-stdin")

    assert User.objects.filter(roles__code="system_admin").count() == 2


@pytest.mark.parametrize(
    ("stdin_text", "args", "message"),
    [
        (STRONG, ["--username=x y"], "lowercase"),
        ("short\n", ["--username=ops.admin"], "too short"),
        ("", ["--username=ops.admin"], "No password"),
    ],
    ids=["bad-username", "weak-password", "empty-stdin"],
)
def test_rejects_invalid_input(monkeypatch, stdin_text, args, message):
    with pytest.raises(CommandError, match=message):
        run(monkeypatch, stdin_text, *args, "--display-name=Ops", "--password-stdin")
    assert not User.objects.exists()


def test_rejects_duplicate_username(monkeypatch, admin_user):
    with pytest.raises(CommandError, match="already exists"):
        run(monkeypatch, STRONG, "--username=admin.one", "--display-name=X", "--password-stdin")


def test_refuses_without_tty_or_stdin_flag(monkeypatch):
    with pytest.raises(CommandError, match="No TTY"):
        run(monkeypatch, STRONG, "--username=ops.admin", "--display-name=Ops")


def test_password_cannot_be_passed_as_argument(monkeypatch):
    with pytest.raises((CommandError, SystemExit)):
        run(monkeypatch, "", "--username=ops.admin", "--display-name=Ops", f"--password={STRONG}")
