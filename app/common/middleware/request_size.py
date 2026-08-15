from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.common.config import get_settings
from app.common.responses.envelope import error_response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    # Multipart framing is not part of the 30 MB image-byte budget.
                    too_large = int(content_length) > get_settings().ai_max_request_bytes + 1_000_000
                except ValueError:
                    too_large = True
                if too_large:
                    return error_response(
                        "UPLOAD_TOO_LARGE",
                        "The request exceeds the configured upload limit.",
                        status_code=413,
                        request_id=getattr(request.state, "request_id", None),
                    )
        return await call_next(request)
