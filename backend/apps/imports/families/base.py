"""Shared import family machinery: columns, row plans, lookups and value checks."""

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.imports.parsing import looks_like_formula


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    required: str = ""  # "" | "always" | "create" | "match"
    help: str = ""
    example: str = ""
    aliases: tuple[str, ...] = ()


@dataclass
class Plan:
    action: str  # create | update | skip | conflict | error
    key: str = ""
    target_id: str = ""
    target_label: str = ""
    messages: list[str] = field(default_factory=list)
    changes: dict = field(default_factory=dict)  # field -> {"before": .., "after": ..}
    data: dict = field(default_factory=dict)  # resolved values for apply (not stored)
    target: object = None


class RowError(ValueError):
    """A value cannot be used; the row becomes an error with this message."""


class ImportRequest:
    """Minimal request for services called by the import worker (audit needs user/META)."""

    def __init__(self, user, job_id):
        self.user = user
        self.META = {"REMOTE_ADDR": "", "HTTP_USER_AGENT": f"import-job/{job_id}"}
        self.headers = {}


class Context:
    def __init__(self, user, mode: str, job, request=None):
        self.user = user
        self.mode = mode
        self.job = job
        self.request = request or ImportRequest(user, job.pk)
        self.permissions = set(user.permission_codes())
        self.cache: dict = {}
        self.seen: dict[str, int] = {}

    def remember(self, key: str, row_number: int) -> int | None:
        """First row that used this key, or None (and remember this row)."""
        first = self.seen.get(key)
        if first is None:
            self.seen[key] = row_number
        return first

    def lookup(self, name: str, loader):
        if name not in self.cache:
            self.cache[name] = loader()
        return self.cache[name]


class Family:
    code = ""
    label = ""
    version = 1
    description = ""
    match_help = ""
    permission = ""  # required to import this family at all
    columns: tuple[Column, ...] = ()
    allow_custom_columns = False  # "cf.<key>" columns (assets)

    def field_names(self) -> set[str]:
        return {c.name for c in self.columns}

    def plan(self, ctx: Context, values: dict[str, str], row_number: int) -> Plan:
        raise NotImplementedError

    def apply(
        self, ctx: Context, plan: Plan, values: dict[str, str]
    ) -> tuple[str, str, int | None]:
        """Apply a create/update plan; returns (target_id, label, version_after)."""
        raise NotImplementedError

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        raise NotImplementedError


# --- Value helpers ---------------------------------------------------------------------------


def text(values: dict, name: str, limit: int = 200) -> str:
    value = (values.get(name) or "").strip()
    if len(value) > limit:
        raise RowError(f"{name}: at most {limit} characters.")
    return value


def check_formulas(values: dict) -> None:
    for name, value in values.items():
        if value and looks_like_formula(value):
            raise RowError(
                f"{name}: looks like a spreadsheet formula ({value[:20]!r}); remove the leading "
                "=, +, @ or - expression."
            )


def find_user(ctx: Context, value: str):
    def load():
        users = {}
        for user in get_user_model().objects.filter(is_active=True):
            users[user.username.lower()] = user
            if getattr(user, "email", ""):
                users.setdefault(user.email.lower(), user)
        return users

    user = ctx.lookup("users", load).get(value.lower())
    if user is None:
        raise RowError(f"No active user {value!r} (use the username or e-mail).")
    return user


def choice(value: str, choices, label: str) -> str:
    lowered = value.strip().lower()
    for code, name in choices:
        if lowered in (str(code).lower(), str(name).lower()):
            return code
    allowed = ", ".join(str(code) for code, _ in choices)
    raise RowError(f"{label}: use one of {allowed}.")


def name_q(field_name: str, value: str) -> Q:
    return Q(**{f"{field_name}__iexact": value})
