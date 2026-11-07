from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def entra_deployment_policy(app_configs, **kwargs):
    from .oidc import ready

    errors = []
    if settings.ITAM_ENTRA_ENABLED:
        if not settings.ITAM_ENTRA_ENFORCE:
            errors.append(
                Error(
                    "Entra test mode permits local pilot sign-in; enforce it before release.",
                    id="accounts.E001",
                )
            )
        if not ready():
            errors.append(
                Error(
                    "Entra requires valid configuration, verified MFA policy, two named admins "
                    "and an explicitly linked admin.",
                    id="accounts.E002",
                )
            )
    elif settings.ITAM_ENV == "production":
        errors.append(
            Error("Production sign-in requires the approved Entra MFA policy.", id="accounts.E003")
        )
    return errors
