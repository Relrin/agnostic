"""RFC 9457 problem details with stable machine-readable ``code`` values."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from agnostic_kernel.context import current_request_id
from agnostic_kernel.logging import get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"

log = get_logger(__name__)


def problem_type(code: str) -> str:
    return f"urn:agnostic:problem:{code}"


class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[FieldError] | None = None


class ProblemResponse(JSONResponse):
    media_type = PROBLEM_MEDIA_TYPE


class AppError(Exception):
    """Base for errors that map to a problem response. Subclasses set ``status``, ``code`` and ``title``."""

    status: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    code: ClassVar[str] = "internal"
    title: ClassVar[str] = "Something went wrong"

    def __init__(self, detail: str | None = None, *, extra: Mapping[str, Any] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.extra: Mapping[str, Any] = extra or {}


class NotFoundError(AppError):
    status = HTTPStatus.NOT_FOUND
    code = "not_found"
    title = "Not found"


class ValidationFailedError(AppError):
    status = HTTPStatus.UNPROCESSABLE_CONTENT
    code = "validation_failed"
    title = "The request is not valid"


class ConflictError(AppError):
    status = HTTPStatus.CONFLICT
    code = "conflict"
    title = "Conflict"


class VersionConflictError(ConflictError):
    code = "version_conflict"
    title = "Someone else changed this first"


class UnauthenticatedError(AppError):
    status = HTTPStatus.UNAUTHORIZED
    code = "unauthenticated"
    title = "Sign in required"


class ScopeMissingError(AppError):
    status = HTTPStatus.FORBIDDEN
    code = "scope_missing"
    title = "You don't have permission to do this"


class ForbiddenError(AppError):
    status = HTTPStatus.FORBIDDEN
    code = "forbidden"
    title = "Not allowed"


class RateLimitedError(AppError):
    status = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    title = "Too many requests"


class ServiceUnavailableError(AppError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "unavailable"
    title = "A dependency is unavailable"


_STATUS_CODES: Mapping[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    422: "validation_failed",
    429: "rate_limited",
}


def problem(
    status: int,
    code: str,
    title: str,
    *,
    detail: str | None = None,
    instance: str | None = None,
    errors: list[FieldError] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> ProblemResponse:
    body = Problem(
        type=problem_type(code),
        title=title,
        status=status,
        code=code,
        detail=detail,
        instance=instance,
        request_id=current_request_id(),
        errors=errors,
    ).model_dump(exclude_none=True)
    body.update(extra or {})
    request_id = current_request_id()
    headers = {"X-Request-Id": request_id} if request_id else None
    return ProblemResponse(body, status_code=status, headers=headers)


async def _app_error(request: Request, exc: Exception) -> ProblemResponse:
    assert isinstance(exc, AppError)
    return problem(exc.status, exc.code, exc.title, detail=exc.detail, instance=request.url.path, extra=exc.extra)


async def _http_error(request: Request, exc: Exception) -> ProblemResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    code = _STATUS_CODES.get(status, "http_error")
    title = HTTPStatus(status).phrase
    detail = exc.detail if exc.detail != title else None
    return problem(status, code, title, detail=detail, instance=request.url.path)


async def _validation_error(request: Request, exc: Exception) -> ProblemResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        FieldError(loc=list(err["loc"]), msg=str(err["msg"]), type=str(err["type"]))  # pyright: ignore[reportAny]
        for err in exc.errors()  # pyright: ignore[reportAny]
    ]
    return problem(
        HTTPStatus.UNPROCESSABLE_CONTENT,
        ValidationFailedError.code,
        ValidationFailedError.title,
        instance=request.url.path,
        errors=errors,
    )


async def _unhandled_error(request: Request, exc: Exception) -> ProblemResponse:
    log.error("unhandled_error", path=request.url.path, exc_info=exc)
    return problem(HTTPStatus.INTERNAL_SERVER_ERROR, AppError.code, AppError.title, instance=request.url.path)


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}, "description": "Client error"},
    "5XX": {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}, "description": "Server error"},
}
"""Declared on ``/api/v1`` so the generated client knows the error shape."""
