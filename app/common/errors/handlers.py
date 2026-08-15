import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from app.common.errors.exceptions import AppError
from app.common.observability import increment
from app.common.responses.envelope import error_response

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if exc.code in {
            "INVALID_IMAGE",
            "IMAGE_DECODE_FAILED",
            "INVALID_IMAGE_DIMENSIONS",
            "INVALID_IMAGE_COUNT",
            "UPLOAD_TOO_LARGE",
            "UNSUPPORTED_MEDIA_TYPE",
        }:
            increment("kok_ai_upload_rejects_total", {"code": exc.code})
        response = error_response(
            exc.code,
            exc.message,
            exc.details,
            exc.status_code,
            getattr(request.state, "request_id", None),
        )
        if isinstance(exc.details, dict) and exc.details.get("retry_after_seconds"):
            response.headers["Retry-After"] = str(exc.details["retry_after_seconds"])
        return response

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        code = "unauthorized" if exc.status_code == 401 else "forbidden" if exc.status_code == 403 else "http_error"
        return error_response(
            code, str(exc.detail), None, exc.status_code, getattr(request.state, "request_id", None)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        safe_details = [
            {"type": error.get("type"), "location": error.get("loc"), "message": error.get("msg")}
            for error in exc.errors()
        ]
        return error_response(
            "validation_error",
            "Request validation failed",
            {"field_errors": safe_details},
            422,
            getattr(request.state, "request_id", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):  # pragma: no cover
        logger.exception(
            "unhandled_request_error",
            extra={
                "request_id": getattr(request.state, "request_id", "unknown"),
                "method": request.method,
                "path": request.url.path,
                "error_type": type(exc).__name__,
            },
        )
        return error_response(
            "INTERNAL_ERROR",
            "Internal server error",
            None,
            500,
            getattr(request.state, "request_id", None),
        )
