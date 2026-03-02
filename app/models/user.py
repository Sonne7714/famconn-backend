from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=80)
    first_name: Optional[str] = Field(default=None, max_length=60)
    last_name: Optional[str] = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()

    @field_validator("password")
    @classmethod
    def _password_policy(cls, v: str) -> str:
        # Minimal sensible policy (no overkill):
        # - at least 8 chars (Field)
        # - at least 1 letter
        # - at least 1 digit
        # - no leading/trailing spaces
        pwd = v.strip()
        if pwd != v:
            raise ValueError("Password must not start or end with spaces")
        if not any(ch.isalpha() for ch in pwd):
            raise ValueError("Password must contain at least one letter")
        if not any(ch.isdigit() for ch in pwd):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class UserPublic(BaseModel):
    id: str = Field(alias="_id")
    email: EmailStr
    display_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    disabled: bool = False
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
