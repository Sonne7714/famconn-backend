from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import get_client_ip, rate_limit_or_429
from app.core.security import create_access_token, create_refresh_token
from app.models.user import (
    AvatarUploadRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserProfileUpdate,
    UserPublic,
    utcnow,
)
from app.services.user_service import UserService

router = APIRouter(tags=["auth"])
bearer = HTTPBearer(auto_error=False)

UPLOAD_DIR = Path("uploads")
AVATAR_DIR = UPLOAD_DIR / "avatars"


def _public_user(user: dict) -> dict:
    return {
        "_id": str(user["_id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "first_name": user.get("first_name") or user.get("display_name"),
        "last_name": user.get("last_name"),
        "avatar_url": user.get("avatar_url"),
        "disabled": bool(user.get("disabled", False)),
        "created_at": user.get("created_at"),
    }


async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = creds.credentials

    from app.core.security import decode_access_token

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await UserService.get_by_id(user_id)
    if not user or user.get("disabled"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def _detect_image_extension(binary: bytes) -> str | None:
    if binary.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if binary.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if binary.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if binary.startswith(b"RIFF") and len(binary) >= 12 and binary[8:12] == b"WEBP":
        return ".webp"
    return None


def _save_avatar_from_data_url(user_id: str, filename: str, data_url: str) -> str:
    match = re.match(r"^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid image data")

    raw_b64 = match.group(2)

    try:
        binary = base64.b64decode(raw_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image encoding")

    if len(binary) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5 MB)")

    ext = _detect_image_extension(binary)
    if not ext:
        raise HTTPException(status_code=400, detail="Only jpg, png, gif or webp allowed")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{user_id}_{uuid.uuid4().hex}{ext}"
    target = AVATAR_DIR / safe_name

    with open(target, "wb") as f:
        f.write(binary)

    return f"/uploads/avatars/{safe_name}"


@router.post("/auth/register", response_model=UserPublic, status_code=201)
async def register(data: UserCreate):
    try:
        user = await UserService.create_user(
            data.email,
            data.password,
            data.display_name,
            first_name=data.first_name,
            last_name=data.last_name,
        )
    except ValueError as e:
        if str(e) == "email_exists":
            raise HTTPException(status_code=409, detail="Email already registered")
        raise
    return _public_user(user)


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request):
    ip = get_client_ip(request)
    rate_limit_or_429(
        request,
        key=f"login:{ip}",
        max_requests=settings.LOGIN_RATE_LIMIT_MAX,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )

    user = await UserService.verify_login(data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access = create_access_token(subject=str(user["_id"]), email=user["email"])
    refresh, refresh_exp = create_refresh_token()
    await UserService.set_refresh_token(str(user["_id"]), refresh, refresh_exp)

    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest):
    from app.core.security import hash_refresh_token

    db = get_db()
    token_hash = hash_refresh_token(data.refresh_token)
    user = await db["users"].find_one({"refresh_token_hash": token_hash})

    if not user:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    ok = await UserService.verify_refresh_token(user, data.refresh_token)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access = create_access_token(subject=str(user["_id"]), email=user["email"])
    new_refresh, refresh_exp = create_refresh_token()
    await UserService.set_refresh_token(str(user["_id"]), new_refresh, refresh_exp)

    return {"access_token": access, "refresh_token": new_refresh, "token_type": "bearer"}


@router.get("/auth/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)):
    return _public_user(user)


@router.patch("/auth/me", response_model=UserPublic)
async def update_me(payload: UserProfileUpdate, user: dict = Depends(get_current_user)):
    updated = await UserService.update_profile(
        str(user["_id"]),
        display_name=payload.display_name,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_user(updated)


@router.post("/auth/me/avatar", response_model=UserPublic)
async def upload_avatar(payload: AvatarUploadRequest, user: dict = Depends(get_current_user)):
    avatar_url = _save_avatar_from_data_url(str(user["_id"]), payload.filename, payload.data_url)

    old_url = (user.get("avatar_url") or "").strip()
    if old_url.startswith("/uploads/avatars/"):
        old_path = Path(old_url.lstrip("/"))
        if old_path.exists():
            try:
                old_path.unlink()
            except Exception:
                pass

    updated = await UserService.set_avatar_url(str(user["_id"]), avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_user(updated)


@router.post("/auth/logout", status_code=204)
async def logout(user: dict = Depends(get_current_user)):
    db = get_db()
    await db["users"].update_one(
        {"_id": ObjectId(str(user["_id"]))},
        {"$set": {"refresh_token_hash": None, "refresh_token_expires_at": None}},
    )
    return None