import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.common.observability import request_id_context
from app.common.request_context import request_origin_context

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.request_id = str(uuid.uuid4())
        token = request_id_context.set(request.state.request_id)
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
        host = request.headers.get("host", "").strip()
        origin = f"{scheme}://{host}" if host and all(char not in host for char in "/\\\r\n") else None
        origin_token = request_origin_context.set(origin)
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
            request_origin_context.reset(origin_token)
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
