from __future__ import annotations

from datetime import datetime
from typing import Optional
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.db import get_db
from app.core.security import hash_password, verify_password, hash_refresh_token
from app.models.user import utcnow

def _oid_str(oid: ObjectId) -> str:
    return str(oid)

class UserService:
    @staticmethod
    async def get_by_email(email: str) -> Optional[dict]:
        db = get_db()
        return await db["users"].find_one({"email": email.strip().lower()})

    @staticmethod
    async def get_by_id(user_id: str) -> Optional[dict]:
        db = get_db()
        if not ObjectId.is_valid(user_id):
            return None
        return await db["users"].find_one({"_id": ObjectId(user_id)})

    @staticmethod
    async def create_user(email: str, password: str, display_name: Optional[str]) -> dict:
        db = get_db()
        doc = {
            "email": email.strip().lower(),
            "password_hash": hash_password(password),
            "display_name": display_name,
            "disabled": False,
            "created_at": utcnow(),
            # refresh token rotation fields:
            "refresh_token_hash": None,
            "refresh_token_expires_at": None,
        }
        try:
            res = await db["users"].insert_one(doc)
        except DuplicateKeyError as e:
            raise ValueError("email_exists") from e
        doc["_id"] = res.inserted_id
        return doc

    @staticmethod
    async def verify_login(email: str, password: str) -> Optional[dict]:
        user = await UserService.get_by_email(email)
        if not user:
            return None
        if user.get("disabled"):
            return None
        if not verify_password(password, user.get("password_hash", "")):
            return None
        return user

    @staticmethod
    async def set_refresh_token(user_id: str, refresh_token: str, refresh_expires_at: datetime) -> None:
        db = get_db()
        await db["users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "refresh_token_hash": hash_refresh_token(refresh_token),
                "refresh_token_expires_at": refresh_expires_at,
            }},
        )

    @staticmethod
    async def verify_refresh_token(user: dict, refresh_token: str) -> bool:
        token_hash = user.get("refresh_token_hash")
        exp = user.get("refresh_token_expires_at")
        if not token_hash or not exp:
            return False

        # Motor/PyMongo often returns naive UTC datetimes; normalize to aware UTC.
        from datetime import timezone
        if getattr(exp, "tzinfo", None) is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > exp:
            return False

        return token_hash == hash_refresh_token(refresh_token)
