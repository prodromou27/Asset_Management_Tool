"""DRF permission classes. Role grants are read from the database each request,
so role changes take effect on the next request without re-login."""

from rest_framework import status
from rest_framework.permissions import BasePermission

from config.api import ApiError


def _authenticated_with_current_password(request) -> bool:
    """Only the allowlisted auth views (me, logout, password change) skip this,
    so an administrator-issued temporary password grants no other access."""
    user = request.user
    if not (user and user.is_authenticated):
        return False
    if user.must_change_password:
        raise ApiError(
            "PASSWORD_CHANGE_REQUIRED",
            "You must change your temporary password before continuing.",
            status.HTTP_403_FORBIDDEN,
        )
    return True


class IsAuthenticatedWithCurrentPassword(BasePermission):
    def has_permission(self, request, view):
        return _authenticated_with_current_password(request)


def HasPermission(*codes: str):  # noqa: N802 - reads like a class at call sites
    """Require every listed permission code."""

    class _HasPermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            if not _authenticated_with_current_password(request):
                return False
            granted = request.user.permission_codes()
            return all(code in granted for code in codes)

    _HasPermission.__name__ = f"HasPermission({', '.join(codes)})"
    return _HasPermission


def HasMethodPermission(read: str, write: str):  # noqa: N802
    """Read permission for safe methods, write permission otherwise."""

    class _HasMethodPermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            if not _authenticated_with_current_password(request):
                return False
            needed = read if request.method in ("GET", "HEAD", "OPTIONS") else write
            return needed in request.user.permission_codes()

    return _HasMethodPermission


def ReadAnyWritePermission(read_any: tuple[str, ...], write: str | tuple[str, ...]):  # noqa: N802
    """Safe methods need any one of `read_any`; unsafe methods need `write` (or any
    one of a tuple of codes; finer checks then happen per field in the service)."""
    write_any = (write,) if isinstance(write, str) else write

    class _ReadAnyWrite(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            if not _authenticated_with_current_password(request):
                return False
            granted = request.user.permission_codes()
            if request.method in ("GET", "HEAD", "OPTIONS"):
                return any(code in granted for code in read_any)
            return any(code in granted for code in write_any)

    return _ReadAnyWrite


def HasAnyPermission(*codes: str):  # noqa: N802
    class _HasAny(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            if not _authenticated_with_current_password(request):
                return False
            granted = request.user.permission_codes()
            return any(code in granted for code in codes)

    return _HasAny
