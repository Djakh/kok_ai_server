import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.common.observability import request_id_context

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.request_id = str(uuid.uuid4())
        token = request_id_context.set(request.state.request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        finally:
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = request.state.request_id
        principal_id = getattr(request.state, "principal_id", "anonymous")
        logger.info(
            "request_completed",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "principal_id": principal_id,
            },
        )
        return response
