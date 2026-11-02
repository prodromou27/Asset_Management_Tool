from rest_framework.authentication import SessionAuthentication


class SessionAuthentication401(SessionAuthentication):
    """Session auth that yields 401 (not 403) for unauthenticated requests."""

    def authenticate_header(self, request):
        return "Session"
