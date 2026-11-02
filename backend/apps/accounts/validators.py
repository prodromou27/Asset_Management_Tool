from django.core.exceptions import ValidationError


class ConfiguredMinimumLengthValidator:
    """Minimum length taken from admin-configurable SecuritySettings."""

    def validate(self, password, user=None):
        from .models import SecuritySettings

        min_length = SecuritySettings.load().password_min_length
        if len(password) < min_length:
            raise ValidationError(
                f"This password is too short. It must contain at least {min_length} characters.",
                code="password_too_short",
            )

    def get_help_text(self):
        from .models import SecuritySettings

        return (
            f"Your password must contain at least "
            f"{SecuritySettings.load().password_min_length} characters."
        )
