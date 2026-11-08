from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def entra_deployment_policy(app_configs, **kwargs):
    from .oidc import ready

    errors = []
    if settings.ITAM_ENTRA_ENABLED:
        if not ready():
            errors.append(
                Error(
                    "Entra requires valid configuration, verified MFA policy, two named admins "
                    "and an explicitly linked admin.",
                    id="accounts.E002",
                )
            )
    return errors
