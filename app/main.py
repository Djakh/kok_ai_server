import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.common.config import get_settings
from app.common.db.session import engine
from app.common.errors.handlers import register_exception_handlers
from app.common.logging.setup import configure_logging
from app.common.middleware.request_id import RequestIDMiddleware
from app.common.middleware.request_size import RequestSizeLimitMiddleware
from app.common.observability import render_prometheus
from app.common.responses.envelope import error_response
from app.common.storage.s3 import ensure_bucket

settings = get_settings()

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    production_errors = settings.production_config_errors()
    if production_errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(production_errors))
    if settings.s3_initialize_bucket_on_startup:
        try:
            await asyncio.to_thread(ensure_bucket)
        except Exception:
            # Readiness and runtime storage operations expose safe deterministic failures.
            pass
    yield

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="1.1.0",
    description=(
        "KOK.AI API. Species and optional visible-condition inference are provided by "
        "third-party Kindwise Plant.id; provider credentials and raw responses are never exposed."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.cors_origins_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["operations"])
def ready(request: Request):
    errors = settings.production_config_errors()
    if not settings.kindwise_api_key and not settings.is_production:
        errors.append("plant analysis provider configuration is missing")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        errors.append("database connectivity check failed")
    if errors:
        return error_response(
            "backend_unavailable",
            "Required service dependencies are not ready.",
            {"checks": errors},
            503,
            getattr(request.state, "request_id", None),
        )
    return {"status": "ready"}


@app.get(f"{settings.api_prefix}/version", tags=["operations"])
def version():
    from app.common.responses.envelope import success_response

    return success_response({"version": app.version, "provider": "kindwise_plant_id"})


@app.get("/metrics", tags=["operations"], include_in_schema=False)
def metrics() -> Response:
    return Response(render_prometheus(), media_type="text/plain; version=0.0.4")
