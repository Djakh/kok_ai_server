from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordRecoveryVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=12)


class PasswordResetRequest(BaseModel):
    reset_token: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class VerificationRequest(BaseModel):
    channel: Literal["email", "phone"]
    phone_number: str | None = Field(default=None, min_length=7, max_length=32)


class VerificationConfirmRequest(BaseModel):
    channel: Literal["email", "phone"]
    code: str = Field(min_length=6, max_length=12)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
