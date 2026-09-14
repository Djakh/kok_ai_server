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
                    settings = get_settings()
                    # Multipart framing and scalar fields are not part of the image-byte budget.
                    maximum_request_bytes = (
                        settings.ai_max_request_bytes
                        + settings.request_multipart_overhead_bytes
                    )
                    too_large = int(content_length) > maximum_request_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    return error_response(
                        "UPLOAD_TOO_LARGE",
                        "The request exceeds the configured upload limit.",
                        {"max_request_bytes": maximum_request_bytes},
                        status_code=413,
                        request_id=getattr(request.state, "request_id", None),
                    )
        return await call_next(request)
