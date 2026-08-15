import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.errors.exceptions import AppError
from app.common.security.jwt import (
    TokenKind,
    decode_token,
    make_access_token,
    make_refresh_token,
)
from app.common.security.password import hash_password, verify_password
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
)
from app.modules.users.models import User, UserRole, UserSettings
from app.modules.users.repository import UserRepository

PASSWORD_POLICY_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)

    def _hash_refresh(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _password_check(self, password: str) -> None:
        if not PASSWORD_POLICY_RE.match(password):
            raise AppError(
                "weak_password",
                "Password must be 8+ chars with letters and digits",
                422,
            )

    def register(self, payload: RegisterRequest) -> TokenPairResponse:
        self._password_check(payload.password)
        if self.users.get_by_email(payload.email):
            raise AppError("email_taken", "Email already registered", 409)
        if self.users.get_by_username(payload.username):
            raise AppError("username_taken", "Username already taken", 409)

        user = User(
            email=payload.email.lower(),
            username=payload.username.strip().lower(),
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
            role=UserRole.USER,
        )
        self.users.create(user)
        self.users.upsert_settings(UserSettings(user_id=user.id))
        tokens = self._issue_tokens(user.id, user.role.value)
        self.db.commit()
        return tokens

    def login(self, payload: LoginRequest) -> TokenPairResponse:
        user = self.users.get_by_email(payload.email)
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppError("invalid_credentials", "Invalid email or password", 401)
        tokens = self._issue_tokens(user.id, user.role.value)
        self.db.commit()
        return tokens

    def refresh(self, payload: RefreshRequest) -> TokenPairResponse:
        token_hash = self._hash_refresh(payload.refresh_token)
        token_row = self.refresh_tokens.by_hash(token_hash)
        if not token_row:
            raise AppError("invalid_refresh", "Invalid refresh token", 401)
        if token_row.revoked:
            self.refresh_tokens.revoke_family(token_row.token_family_id)
            self.db.commit()
            raise AppError("invalid_refresh", "Refresh token reuse detected", 401)
        if token_row.expires_at < datetime.now(timezone.utc):
            raise AppError("refresh_expired", "Refresh token expired", 401)

        try:
            claims = decode_token(payload.refresh_token, TokenKind.REFRESH)
        except Exception as exc:
            raise AppError("invalid_refresh", "Invalid refresh token", 401) from exc

        self.refresh_tokens.revoke(token_row)
        token_row.rotated_at = datetime.now(timezone.utc)
        tokens = self._issue_tokens(
            uuid.UUID(claims["sub"]), claims["role"], token_row.token_family_id
        )
        self.db.commit()
        return tokens

    def logout(self, refresh_token: str) -> None:
        token_hash = self._hash_refresh(refresh_token)
        token_row = self.refresh_tokens.by_hash(token_hash)
        if token_row:
            self.refresh_tokens.revoke(token_row)
            self.db.commit()

    def _issue_tokens(
        self, user_id: uuid.UUID, role: str, family_id: uuid.UUID | None = None
    ) -> TokenPairResponse:
        family_id = family_id or uuid.uuid4()
        session_uuid = uuid.uuid4()
        session_id = str(session_uuid)
        access = make_access_token(str(user_id), role, session_id)
        refresh = make_refresh_token(str(user_id), role, session_id)
        refresh_hash = self._hash_refresh(refresh)
        row = RefreshToken(
            id=session_uuid,
            user_id=user_id,
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=get_settings().jwt_refresh_expire_days),
            created_at=datetime.now(timezone.utc),
            token_family_id=family_id,
        )
        self.refresh_tokens.create(row)
        return TokenPairResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=get_settings().jwt_access_expire_minutes * 60,
        )
