from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING

from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db = None


async def connect_to_mongo():
    """
    Called on FastAPI startup.
    Establish Mongo connection and create required indexes.
    """
    global _client, _db

    _client = AsyncIOMotorClient(settings.MONGO_URI)
    _db = _client[settings.MONGO_DB]

    # ======================
    # Users
    # ======================
    await _db["users"].create_index(
        [("email", ASCENDING)],
        unique=True
    )

    # ======================
    # Families
    # ======================
    await _db["families"].create_index("owner_id")

    # ======================
    # Family Members
    # Prevent duplicate membership
    # ======================
    await _db["family_members"].create_index(
        [("family_id", ASCENDING), ("user_id", ASCENDING)],
        unique=True
    )

    # ======================
    # Invitations
    # TTL index (auto delete expired invites)
    # ======================
    await _db["invitations"].create_index(
        "expires_at",
        expireAfterSeconds=0
    )


async def close_mongo_connection():
    """
    Called on FastAPI shutdown.
    """
    global _client
    if _client:
        _client.close()


def get_db():
    """
    FastAPI dependency that returns database instance.
    """
    if _db is None:
        raise RuntimeError("MongoDB is not connected.")
    return _db