from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import jwt, JWTError

from app.core.config import settings

ph = PasswordHasher(time_cost=2, memory_cost=102400, parallelism=8)

@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False

def _now() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(subject: str, email: str) -> str:
    exp = _now() + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": subject,
        "email": email,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(_now().timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def create_refresh_token() -> tuple[str, datetime]:
    # opaque token, stored as hash in DB (rotation friendly)
    token = secrets.token_urlsafe(48)
    exp = _now() + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    return token, exp

def hash_refresh_token(token: str) -> str:
    # store only a one-way hash
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"require_aud": True, "require_iss": True},
        )
    except JWTError as e:
        raise ValueError("Invalid token") from e

    if payload.get("typ") != "access":
        raise ValueError("Invalid token type")
    return payload
