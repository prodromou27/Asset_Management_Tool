"""SMTP transport (docs/10 "Configurable settings").

- STARTTLS is required when chosen: if the server does not offer it the connection fails;
  it never continues in plain text. Implicit TLS uses SMTPS. Certificates and host names are
  always validated (system CAs, or a CA bundle file from the secrets directory).
- Credentials are sent only over TLS; the password is resolved from its secret reference
  at connect time and never logged or returned.
- Errors are classified: connection-level problems (DNS, refused, timeout, TLS, login,
  4xx) are temporary for the message; a 5xx answer to the message or recipient is
  permanent (bounce).
"""

import smtplib
import socket
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from apps.integrations import secrets

from .models import SmtpProfile


class ConfigError(Exception):
    """The profile cannot be used as configured (not retried until changed)."""


class TemporaryFailure(Exception):
    pass


class PermanentFailure(Exception):
    pass


def _context(profile: SmtpProfile) -> ssl.SSLContext:
    try:
        cafile = secrets.resolve_path(profile.ca_bundle_ref) if profile.ca_bundle_ref else None
    except secrets.SecretError as exc:
        raise ConfigError(str(exc)) from exc
    context = ssl.create_default_context(cafile=cafile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _password(profile: SmtpProfile) -> str:
    try:
        return secrets.resolve(profile.password_ref, secrets.SMTP)
    except secrets.SecretError as exc:
        raise ConfigError(f"SMTP password: {exc}") from exc


def check_profile(profile: SmtpProfile) -> None:
    if not profile.host:
        raise ConfigError("Enter the SMTP host.")
    if not profile.from_address:
        raise ConfigError("Enter the sender address.")
    if profile.uses_auth and profile.security == SmtpProfile.Security.NONE:
        raise ConfigError("Credentials are only sent over STARTTLS or implicit TLS.")
    if profile.uses_auth and not profile.password_ref:
        raise ConfigError("Enter the password reference for the SMTP user.")


def _describe(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPResponseException):
        text = (
            exc.smtp_error.decode("utf-8", "replace")
            if isinstance(exc.smtp_error, bytes)
            else str(exc.smtp_error)
        )
        return f"{exc.smtp_code} {text}"[:300]
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f"TLS certificate not trusted: {exc.verify_message}"
    if isinstance(exc, ssl.SSLError):
        return f"TLS error: {exc.reason or exc}"
    if isinstance(exc, TimeoutError | socket.timeout):
        return "Timed out"
    if isinstance(exc, socket.gaierror):
        return "Host name does not resolve"
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused"
    return str(exc)[:300] or exc.__class__.__name__


@contextmanager
def connect(profile: SmtpProfile):
    """An authenticated SMTP session according to the profile."""
    check_profile(profile)
    password = _password(profile) if profile.uses_auth else ""
    context = _context(profile)
    timeout = profile.timeout_seconds
    try:
        if profile.security == SmtpProfile.Security.TLS:
            client = smtplib.SMTP_SSL(profile.host, profile.port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(profile.host, profile.port, timeout=timeout)
    except (OSError, smtplib.SMTPException) as exc:
        raise TemporaryFailure(
            f"Cannot connect to {profile.host}:{profile.port}: {_describe(exc)}"
        ) from exc
    try:
        try:
            client.ehlo()
            if profile.security == SmtpProfile.Security.STARTTLS:
                if not client.has_extn("starttls"):
                    raise TemporaryFailure(
                        "The server does not offer STARTTLS; ITAM does not continue unencrypted."
                    )
                client.starttls(context=context)
                client.ehlo()
            if profile.uses_auth:
                client.login(profile.username, password)
        except smtplib.SMTPAuthenticationError as exc:
            raise TemporaryFailure(f"Login refused: {_describe(exc)}") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise TemporaryFailure(_describe(exc)) from exc
        yield client
    finally:
        try:
            client.quit()
        except (OSError, smtplib.SMTPException):
            client.close()


def build(profile: SmtpProfile, to: str, subject: str, text: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((profile.from_name, profile.from_address))
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False, usegmt=True)
    domain = profile.from_address.rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    if profile.reply_to:
        message["Reply-To"] = profile.reply_to
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def send(client, message: EmailMessage) -> None:
    try:
        refused = client.send_message(message)
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        detail = "; ".join(
            f"{code} {msg.decode('utf-8', 'replace') if isinstance(msg, bytes) else msg}"
            for code, msg in exc.recipients.values()
        )[:300]
        if all(code >= 500 for code in codes):
            raise PermanentFailure(f"Recipient refused: {detail}") from exc
        raise TemporaryFailure(f"Recipient deferred: {detail}") from exc
    except smtplib.SMTPResponseException as exc:
        if 500 <= exc.smtp_code < 600:
            raise PermanentFailure(_describe(exc)) from exc
        raise TemporaryFailure(_describe(exc)) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise TemporaryFailure(_describe(exc)) from exc
    if refused:
        raise PermanentFailure(f"Recipient refused: {next(iter(refused.values()))}")
