"""Restricted template rendering (docs/10: "Rendering must escape user-controlled values and
not embed secret content").

Templates use a small, whitelisted subset of the Django template language: no ``load``,
``include``, ``extends``, ``url`` or ``safe``-style filters, so a template cannot read files,
call code or switch escaping off. HTML bodies are auto-escaped; subjects lose line breaks
(no header injection). Producers pass plain values only (strings, numbers, dates, lists and
dicts of those); never model instances or secrets.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.template import Context, Engine, TemplateSyntaxError

ALLOWED_TAGS = {
    "if",
    "elif",
    "else",
    "endif",
    "for",
    "empty",
    "endfor",
    "with",
    "endwith",
    "comment",
    "endcomment",
    "spaceless",
    "endspaceless",
}
ALLOWED_FILTERS = {
    "date",
    "time",
    "default",
    "default_if_none",
    "upper",
    "lower",
    "title",
    "capfirst",
    "length",
    "pluralize",
    "join",
    "yesno",
    "floatformat",
    "truncatechars",
    "truncatewords",
    "linebreaksbr",
    "first",
    "last",
    "slice",
    "add",
    "stringformat",
    "escape",
    "urlencode",
}
TAG = re.compile(r"{%-?\s*(\w+)")
FILTER = re.compile(r"\|\s*(\w+)")
VARIABLE_BLOCK = re.compile(r"{{(.*?)}}|{%(.*?)%}", re.S)

_ENGINE = Engine(
    debug=False,
    libraries={},
    builtins=["django.template.defaulttags", "django.template.defaultfilters"],
    string_if_invalid="",
)


class TemplateError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def check(field: str, source: str) -> None:
    """Refuse tags/filters outside the whitelist and anything that does not parse."""
    for name in TAG.findall(source):
        if name not in ALLOWED_TAGS:
            raise TemplateError(field, f"The tag {{% {name} %}} is not allowed in templates.")
    for block in VARIABLE_BLOCK.finditer(source):
        text = block.group(1) or block.group(2) or ""
        for name in FILTER.findall(text):
            if name not in ALLOWED_FILTERS:
                raise TemplateError(field, f"The filter |{name} is not allowed in templates.")
    try:
        _ENGINE.from_string(source)
    except TemplateSyntaxError as exc:
        raise TemplateError(field, f"Template error: {exc}") from exc


@dataclass
class Rendered:
    subject: str
    body_text: str
    body_html: str


def app_url() -> str:
    """Link to the web UI: first allowed host with the public scheme."""
    hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")]
    scheme = getattr(settings, "PUBLIC_SCHEME", "https")
    return f"{scheme}://{hosts[0]}" if hosts else ""


def base_context() -> dict:
    return {"app_name": "ITAM", "app_url": app_url(), "now": datetime.now(UTC)}


def render(subject: str, body_text: str, body_html: str, context: dict) -> Rendered:
    for field, source in (("subject", subject), ("body_text", body_text), ("body_html", body_html)):
        check(field, source)
    values = {**base_context(), **context}
    plain = Context(values, autoescape=False)
    subject_out = _ENGINE.from_string(subject).render(plain)
    subject_out = " ".join(subject_out.replace("\r", " ").replace("\n", " ").split())[:300]
    text_out = _ENGINE.from_string(body_text).render(Context(values, autoescape=False))
    html_out = ""
    if body_html.strip():
        html_out = _ENGINE.from_string(body_html).render(Context(values, autoescape=True))
    return Rendered(subject=subject_out, body_text=text_out.strip() + "\n", body_html=html_out)
