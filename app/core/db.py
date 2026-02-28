from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB not initialized. Did you miss startup event?")
    return _db

async def connect_to_mongo() -> None:
    global _client, _db
    if not settings.MONGO_URI:
        raise RuntimeError("MONGO_URI is not set. Please configure it in .env")
    _client = AsyncIOMotorClient(settings.MONGO_URI)
    _db = _client[settings.MONGO_DB]

    # Ensure indexes (idempotent, and safe if index options changed)
    users = _db["users"]
    info = await users.index_information()

    async def ensure_index(name: str, keys, **opts) -> None:
        existing = info.get(name)
        if existing:
            mismatch = False
            if existing.get("key") != keys:
                mismatch = True
            for k, v in opts.items():
                if existing.get(k) != v:
                    mismatch = True
                    break
            if mismatch:
                await users.drop_index(name)
                await users.create_index(keys, name=name, **opts)
        else:
            await users.create_index(keys, name=name, **opts)

    # Unique email (prevents duplicate accounts)
    await ensure_index("email_1", [("email", 1)], unique=True)

    # Refresh-token hash index (sparse allows missing field without collisions)
    await ensure_index("refresh_token_hash_1", [("refresh_token_hash", 1)], sparse=True)

    # Ensure indexes (minimal)
    await _db["users"].create_index("email", unique=True)
    await _db["users"].create_index("refresh_token_hash", sparse=True)

async def close_mongo_connection() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
