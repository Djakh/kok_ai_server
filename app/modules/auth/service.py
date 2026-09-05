import hashlib
import re
import secrets
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
from app.modules.auth.models import RefreshToken, VerificationChallenge
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    VerificationRequest,
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
        if (
            not user
            or not user.is_active
            or not verify_password(payload.password, user.password_hash)
        ):
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

    def request_password_recovery(self, email: str) -> dict:
        user = self.users.get_by_email(email)
        response: dict[str, object] = {"accepted": True, "expires_in": 600}
        if not user:
            return response
        code = self._create_challenge(user.id, "password_reset", user.email)
        self.db.commit()
        if not get_settings().is_production:
            response["debug_code"] = code
        return response

    def verify_password_recovery(self, email: str, code: str) -> dict:
        challenge = self._verify_challenge("password_reset", email.lower(), code)
        reset_token = secrets.token_urlsafe(32)
        challenge.reset_token_hash = self._hash_refresh(reset_token)
        challenge.verified_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"verified": True, "reset_token": reset_token, "expires_at": challenge.expires_at}

    def reset_password(self, reset_token: str, new_password: str) -> None:
        self._password_check(new_password)
        token_hash = self._hash_refresh(reset_token)
        challenge = (
            self.db.query(VerificationChallenge)
            .filter(
                VerificationChallenge.reset_token_hash == token_hash,
                VerificationChallenge.purpose == "password_reset",
                VerificationChallenge.verified_at.is_not(None),
                VerificationChallenge.consumed_at.is_(None),
            )
            .first()
        )
        if (
            not challenge
            or challenge.expires_at < datetime.now(timezone.utc)
            or not challenge.user_id
        ):
            raise AppError(
                "invalid_reset_token", "Password reset token is invalid or expired.", 422
            )
        user = self.users.get_by_id(challenge.user_id)
        if not user:
            raise AppError(
                "invalid_reset_token", "Password reset token is invalid or expired.", 422
            )
        user.password_hash = hash_password(new_password)
        challenge.consumed_at = datetime.now(timezone.utc)
        self.refresh_tokens.revoke_for_user(user.id)
        self.db.commit()

    def request_verification(self, user: User, payload: VerificationRequest) -> dict:
        destination = user.email
        purpose = "verify_email"
        if payload.channel == "phone":
            if not payload.phone_number:
                raise AppError("validation_error", "phone_number is required.", 422)
            destination = payload.phone_number
            purpose = "verify_phone"
            user.phone_number = destination
        code = self._create_challenge(user.id, purpose, destination)
        self.db.commit()
        response: dict[str, object] = {
            "accepted": True,
            "channel": payload.channel,
            "expires_in": 600,
        }
        if not get_settings().is_production:
            response["debug_code"] = code
        return response

    def confirm_verification(self, user: User, channel: str, code: str) -> dict:
        purpose = "verify_email" if channel == "email" else "verify_phone"
        destination = user.email if channel == "email" else user.phone_number
        if not destination:
            raise AppError("verification_not_requested", "Verification was not requested.", 409)
        challenge = self._verify_challenge(purpose, destination, code)
        now = datetime.now(timezone.utc)
        challenge.verified_at = now
        challenge.consumed_at = now
        if channel == "email":
            user.email_verified_at = now
        else:
            user.phone_verified_at = now
        self.db.commit()
        return {"verified": True, "channel": channel, "verified_at": now}

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AppError("invalid_credentials", "Current password is incorrect.", 401)
        self._password_check(new_password)
        user.password_hash = hash_password(new_password)
        self.refresh_tokens.revoke_for_user(user.id)
        self.db.commit()

    def sessions(self, user_id: uuid.UUID, current_session_id: str | None) -> list[dict]:
        return [
            {
                "id": str(row.id),
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "last_rotated_at": row.rotated_at,
                "user_agent": row.user_agent,
                "ip_address": row.ip_address,
                "is_current": str(row.id) == current_session_id,
            }
            for row in self.refresh_tokens.active_for_user(user_id)
        ]

    def revoke_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        if not self.refresh_tokens.revoke_for_user(user_id, session_id):
            raise AppError("session_not_found", "Session was not found.", 404)
        self.db.commit()

    def revoke_all_sessions(self, user_id: uuid.UUID) -> None:
        self.refresh_tokens.revoke_for_user(user_id)
        self.db.commit()

    def _create_challenge(self, user_id: uuid.UUID, purpose: str, destination: str) -> str:
        now = datetime.now(timezone.utc)
        self.db.query(VerificationChallenge).filter(
            VerificationChallenge.user_id == user_id,
            VerificationChallenge.purpose == purpose,
            VerificationChallenge.consumed_at.is_(None),
        ).update({VerificationChallenge.consumed_at: now}, synchronize_session=False)
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.db.add(
            VerificationChallenge(
                user_id=user_id,
                purpose=purpose,
                destination=destination.lower() if purpose != "verify_phone" else destination,
                code_hash=self._hash_refresh(code),
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        return code

    def _verify_challenge(self, purpose: str, destination: str, code: str) -> VerificationChallenge:
        challenge = (
            self.db.query(VerificationChallenge)
            .filter(
                VerificationChallenge.purpose == purpose,
                VerificationChallenge.destination == destination,
                VerificationChallenge.consumed_at.is_(None),
            )
            .order_by(VerificationChallenge.created_at.desc())
            .first()
        )
        now = datetime.now(timezone.utc)
        if not challenge or challenge.expires_at < now or challenge.attempts >= 5:
            raise AppError("verification_expired", "Verification code is invalid or expired.", 422)
        if not secrets.compare_digest(challenge.code_hash, self._hash_refresh(code)):
            challenge.attempts += 1
            self.db.commit()
            raise AppError("invalid_verification_code", "Verification code is invalid.", 422)
        return challenge

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
