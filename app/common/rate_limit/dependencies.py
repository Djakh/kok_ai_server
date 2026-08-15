from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Header

from app.common.cache.redis_client import redis_client
from app.common.config import get_settings
from app.common.errors.exceptions import AppError
from app.common.security.dependencies import CurrentUser, get_current_user

settings = get_settings()



def _limiter(prefix: str, per_minute: int, key: str) -> None:
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d%H%M")
    redis_key = f"ratelimit:{prefix}:{key}:{bucket}"
    try:
        value: Any = redis_client.incr(redis_key)
        if value == 1:
            redis_client.expire(redis_key, 65)
        if value > per_minute:
            raise AppError(
                "rate_limited", "Too many requests.", 429, {"retry_after_seconds": 60}
            )
    except AppError:
        raise
    except Exception as exc:
        if settings.is_production:
            raise AppError("backend_unavailable", "Rate limiting is unavailable.", 503) from exc



def auth_rate_limit(x_forwarded_for: str | None = Header(default=None)) -> None:
    key = x_forwarded_for or "anonymous"
    _limiter("auth", settings.rate_limit_auth_per_minute, key)


def auth_identity_rate_limit(identity: str) -> None:
    _limiter("auth-identity", settings.rate_limit_auth_per_minute, identity.strip().lower())



def write_rate_limit(x_forwarded_for: str | None = Header(default=None)) -> None:
    key = x_forwarded_for or "anonymous"
    _limiter("write", settings.rate_limit_write_per_minute, key)


def analysis_rate_limit(
    current: CurrentUser = Depends(get_current_user),
    x_forwarded_for: str | None = Header(default=None),
) -> None:
    _limiter(
        "analysis-user",
        settings.analysis_rate_limit_per_minute,
        str(current.user.id),
    )
    if x_forwarded_for:
        client_ip = x_forwarded_for.split(",", 1)[0].strip()
        _limiter("analysis-client", settings.analysis_rate_limit_per_minute, client_ip)


AuthRateLimit = Depends(auth_rate_limit)
WriteRateLimit = Depends(write_rate_limit)
AnalysisRateLimit = Depends(analysis_rate_limit)
