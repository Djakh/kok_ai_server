import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.common.config import get_settings

settings = get_settings()


class TokenKind:
    ACCESS = "access"
    REFRESH = "refresh"


def create_token(
    subject: str,
    role: str,
    kind: str,
    expires_delta: timedelta,
    session_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "sid": session_id or str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
    }
    secret = settings.jwt_access_secret if kind == TokenKind.ACCESS else settings.jwt_refresh_secret
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, kind: str) -> dict[str, Any]:
    secret = settings.jwt_access_secret if kind == TokenKind.ACCESS else settings.jwt_refresh_secret
    return jwt.decode(token, secret, algorithms=["HS256"])


def make_access_token(user_id: str, role: str, session_id: str | None = None) -> str:
    return create_token(
        subject=user_id,
        role=role,
        kind=TokenKind.ACCESS,
        expires_delta=timedelta(minutes=settings.jwt_access_expire_minutes),
        session_id=session_id,
    )


def make_refresh_token(user_id: str, role: str, session_id: str | None = None) -> str:
    return create_token(
        subject=user_id,
        role=role,
        kind=TokenKind.REFRESH,
        expires_delta=timedelta(days=settings.jwt_refresh_expire_days),
        session_id=session_id,
    )
