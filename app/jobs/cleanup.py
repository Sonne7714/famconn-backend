from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

from app.core.db import connect_to_mongo, close_mongo_connection, get_db

UTC = timezone.utc
USER_DELETE_DAYS = 30

async def run_cleanup():
    await connect_to_mongo()
    db = get_db()

    cutoff = datetime.now(UTC) - timedelta(days=USER_DELETE_DAYS)

    async for user in db["users"].find({"created_at": {"$lte": cutoff}}):
        member = await db["family_members"].find_one({"user_id": user["_id"]})
        if not member:
            await db["users"].delete_one({"_id": user["_id"]})

    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_cleanup())
