"""Cross-cutting DRF behaviour implementing docs/04_API_CONTRACT.md."""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response

from config.request_context import get_request_id


class ApiError(exceptions.APIException):
    """Domain error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, http_status: int, field_errors=None):
        super().__init__(detail=message, code=code)
        self.status_code = http_status
        self.error_code = code
        self.field_errors = field_errors or {}


_DEFAULT_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    412: "VERSION_MISMATCH",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    428: "PRECONDITION_REQUIRED",
    429: "TOO_MANY_REQUESTS",
}


def _flatten(detail):
    if isinstance(detail, list):
        return [str(item) for item in detail]
    if isinstance(detail, dict):
        return {key: _flatten(value) for key, value in detail.items()}
    return [str(detail)]


def api_exception_handler(exc, context):
    from rest_framework.views import exception_handler  # lazy: avoids DRF import cycle

    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None

    field_errors = {}
    if isinstance(exc, ApiError):
        code, message, field_errors = exc.error_code, str(exc.detail), exc.field_errors
    elif isinstance(exc, exceptions.ValidationError):
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        code, message = "VALIDATION_ERROR", "The submitted data is invalid."
        detail = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        field_errors = _flatten(detail)
    else:
        code = _DEFAULT_CODES.get(response.status_code, "ERROR")
        message = str(exc.detail) if hasattr(exc, "detail") else str(exc)

    response.data = {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
            "field_errors": field_errors,
        }
    }
    return response


class ItemsCursorPagination(CursorPagination):
    """Cursor pagination returning {items, next_cursor, previous_cursor, count}."""

    page_size = 50
    max_page_size = 200
    page_size_query_param = "page_size"
    ordering = "-created_at"

    def paginate_queryset(self, queryset, request, view=None):
        self._count = queryset.count()
        return super().paginate_queryset(queryset, request, view)

    def _cursor_param(self, url):
        if not url:
            return None
        from urllib.parse import parse_qs, urlparse

        return parse_qs(urlparse(url).query).get(self.cursor_query_param, [None])[0]

    def get_paginated_response(self, data):
        return Response(
            {
                "items": data,
                "next_cursor": self._cursor_param(self.get_next_link()),
                "previous_cursor": self._cursor_param(self.get_previous_link()),
                "count": self._count,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "required": ["items", "next_cursor", "previous_cursor", "count"],
            "properties": {
                "items": schema,
                "next_cursor": {"type": "string", "nullable": True},
                "previous_cursor": {"type": "string", "nullable": True},
                "count": {"type": "integer"},
            },
        }


def require_if_match(request, current_version: int) -> None:
    """Optimistic concurrency: PATCH must carry If-Match with the current version."""
    header = request.headers.get("If-Match")
    if header is None:
        raise ApiError(
            "PRECONDITION_REQUIRED",
            "If-Match header with the current version is required.",
            status.HTTP_428_PRECONDITION_REQUIRED,
        )
    if header.strip('"W/ ') != str(current_version):
        raise ApiError(
            "VERSION_MISMATCH",
            "This record was changed by someone else. Reload and try again.",
            status.HTTP_409_CONFLICT,
        )
