from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import OperationFailure

from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db = None


async def _safe_create_index(collection, keys, **kwargs):
    try:
        await collection.create_index(keys, **kwargs)
    except OperationFailure:
        # Index already exists or options conflict: keep startup alive
        return
    except Exception:
        return


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
    await _safe_create_index(_db["users"], [("email", ASCENDING)], unique=True, name="email_unique")

    # ======================
    # Families
    # ======================
    await _safe_create_index(_db["families"], "owner_id", name="families_owner_id")

    # ======================
    # Family Members
    # Prevent duplicate membership
    # ======================
    await _safe_create_index(
        _db["family_members"],
        [("family_id", ASCENDING), ("user_id", ASCENDING)],
        unique=True,
        name="family_members_unique",
    )
    await _safe_create_index(_db["family_members"], "family_id", name="family_members_family_id")
    await _safe_create_index(_db["family_members"], "user_id", name="family_members_user_id")

    # ======================
    # Invitations
    # TTL index (auto delete expired invites)
    # ======================
    await _safe_create_index(_db["invitations"], "expires_at", expireAfterSeconds=0, name="invites_ttl")
    await _safe_create_index(_db["invitations"], [("code", ASCENDING)], unique=True, name="invites_code_unique")
    await _safe_create_index(_db["invitations"], "family_id", name="invites_family_id")
    await _safe_create_index(_db["invitations"], [("family_id", ASCENDING), ("used", ASCENDING)], name="invites_family_used")


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
