from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.user import UserCreate, UserLogin, UserPublic, TokenResponse, RefreshRequest, utcnow
from app.services.user_service import UserService
from app.core.security import create_access_token, create_refresh_token
from app.core.config import settings
from app.core.ratelimit import get_client_ip, rate_limit_or_429

router = APIRouter(tags=["auth"])
bearer = HTTPBearer(auto_error=False)

def _public_user(user: dict) -> dict:
    # remove sensitive fields
    return {
        "_id": str(user["_id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "first_name": user.get("first_name") or user.get("display_name"),
        "last_name": user.get("last_name"),
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

@router.post("/auth/register", response_model=UserPublic, status_code=201)
async def register(data: UserCreate):
    try:
        user = await UserService.create_user(data.email, data.password, data.display_name, first_name=data.first_name, last_name=data.last_name)
    except ValueError as e:
        if str(e) == "email_exists":
            raise HTTPException(status_code=409, detail="Email already registered")
        raise
    return _public_user(user)

@router.post("/auth/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request):
    # Rate limit by client IP (simple in-memory limiter)
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
    # Find user by stored refresh hash: easiest is to require email? We avoid that.
    # We'll locate user by scanning on hash (indexed? not yet). For MVP ok; later: store refresh jti.
    from app.core.security import hash_refresh_token
    from app.core.db import get_db
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


@router.post("/auth/logout", status_code=204)
async def logout(user: dict = Depends(get_current_user)):
    # Invalidate refresh token on this account (simple single-session approach)
    await UserService.set_refresh_token(str(user["_id"]), refresh_token="", refresh_expires_at=utcnow())
    # Also clear fields to None for cleanliness
    from app.core.db import get_db
    from bson import ObjectId
    db = get_db()
    await db["users"].update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": {"refresh_token_hash": None, "refresh_token_expires_at": None}},
    )
    return None
