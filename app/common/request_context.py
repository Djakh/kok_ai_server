from contextvars import ContextVar

request_origin_context: ContextVar[str | None] = ContextVar(
    "request_origin_context",
    default=None,
)
