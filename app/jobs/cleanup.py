from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from app.core.db import connect_to_mongo, close_mongo_connection, get_db
from app.services.mailer import send_email

UTC = timezone.utc

# ------------------------
# ENTERPRISE STANDARD POLICY
# ------------------------
# Users WITHOUT family:
#   warn at day 23
#   soft-delete at day 30  (disabled=True)
#   hard-delete at day 37
USER_WARN_DAYS = 23
USER_SOFT_DELETE_DAYS = 30
USER_HARD_DELETE_DAYS = 37

# Families with ZERO members and ZERO invites/activity:
#   warn at day 83
#   soft-delete at day 90
#   hard-delete at day 97
FAM_WARN_DAYS = 83
FAM_SOFT_DELETE_DAYS = 90
FAM_HARD_DELETE_DAYS = 97

# Safety nets
MAX_USER_HARD_DELETES_PER_RUN = 500
MAX_FAM_HARD_DELETES_PER_RUN = 200


def now_utc() -> datetime:
    return datetime.now(UTC)


def cutoff(days: int) -> datetime:
    return now_utc() - timedelta(days=days)


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
    return None


def _inactive_since(doc: dict) -> datetime | None:
    return _dt(doc.get("last_active_at")) or _dt(doc.get("created_at"))


async def _user_has_family(db, user_id: ObjectId) -> bool:
    m = await db["family_members"].find_one({"user_id": user_id}, {"_id": 1})
    return m is not None


async def _family_activity_ts(db, family_id: ObjectId, family_doc: dict) -> datetime | None:
    base = _dt(family_doc.get("created_at"))
    latest = base

    m = await db["family_members"].find_one(
        {"family_id": family_id},
        sort=[("created_at", -1)],
        projection={"created_at": 1},
    )
    if m:
        t = _dt(m.get("created_at"))
        if t and (latest is None or t > latest):
            latest = t

    inv = await db["invitations"].find_one(
        {"family_id": family_id},
        sort=[("created_at", -1)],
        projection={"created_at": 1},
    )
    if inv:
        t = _dt(inv.get("created_at"))
        if t and (latest is None or t > latest):
            latest = t

    return latest


def _log(msg: str) -> None:
    print(f"[cleanup] {msg}", flush=True)


async def run_cleanup() -> None:
    await connect_to_mongo()
    db = get_db()
    now = now_utc()

    stats = {
        "users_warned": 0,
        "users_soft_deleted": 0,
        "users_hard_deleted": 0,
        "families_warned": 0,
        "families_soft_deleted": 0,
        "families_hard_deleted": 0,
    }

    # ---------------- USERS (no family) ----------------
    warn_before = cutoff(USER_WARN_DAYS)
    soft_before = cutoff(USER_SOFT_DELETE_DAYS)
    hard_before = cutoff(USER_HARD_DELETE_DAYS)

    # 1) WARN
    cursor = db["users"].find(
        {
            "deletion_warned_at": {"$exists": False},
            "disabled": {"$ne": True},
        },
        projection={"_id": 1, "email": 1, "created_at": 1, "last_active_at": 1},
    )

    async for u in cursor:
        uid = u["_id"]
        inactive = _inactive_since(u)
        if not inactive or inactive > warn_before:
            continue
        if await _user_has_family(db, uid):
            continue

        email = u.get("email")
        if email:
            send_email(
                to=email,
                subject="FamConn: Konto wird in 7 Tagen gelöscht",
                text=(
                    "Hallo,\n\n"
                    "dein FamConn-Konto ist seit einiger Zeit inaktiv und gehört keiner Familie an.\n"
                    "Wenn du dein Konto behalten möchtest, melde dich bitte innerhalb der nächsten 7 Tage an.\n\n"
                    "Viele Grüße\nFamConn"
                ),
            )
        await db["users"].update_one({"_id": uid}, {"$set": {"deletion_warned_at": now}})
        stats["users_warned"] += 1

    # 2) SOFT DELETE (disable account)
    cursor = db["users"].find(
        {"disabled": {"$ne": True}},
        projection={"_id": 1, "created_at": 1, "last_active_at": 1},
    )
    async for u in cursor:
        uid = u["_id"]
        inactive = _inactive_since(u)
        if not inactive or inactive > soft_before:
            continue
        if await _user_has_family(db, uid):
            continue

        await db["users"].update_one(
            {"_id": uid},
            {"$set": {"disabled": True, "deactivated_at": now}},
        )
        stats["users_soft_deleted"] += 1

    # 3) HARD DELETE
    hard_deleted = 0
    cursor = db["users"].find(
        {"disabled": True, "deactivated_at": {"$lte": hard_before}},
        projection={"_id": 1},
    )
    async for u in cursor:
        if hard_deleted >= MAX_USER_HARD_DELETES_PER_RUN:
            _log(f"Safety stop: max user hard deletes reached ({MAX_USER_HARD_DELETES_PER_RUN}).")
            break

        uid = u["_id"]
        if await _user_has_family(db, uid):
            continue

        await db["family_members"].delete_many({"user_id": uid})
        await db["invitations"].delete_many({"created_by": uid})
        await db["users"].delete_one({"_id": uid})

        hard_deleted += 1
        stats["users_hard_deleted"] += 1

    # ---------------- FAMILIES (unused) ----------------
    fam_warn_before = cutoff(FAM_WARN_DAYS)
    fam_soft_before = cutoff(FAM_SOFT_DELETE_DAYS)
    fam_hard_before = cutoff(FAM_HARD_DELETE_DAYS)

    fam_cursor = db["families"].find(
        {"deleted": {"$ne": True}},
        projection={"_id": 1, "name": 1, "owner_id": 1, "created_at": 1, "deletion_warned_at": 1, "deactivated_at": 1},
    )

    async for fam in fam_cursor:
        fid = fam["_id"]

        member = await db["family_members"].find_one({"family_id": fid}, {"_id": 1})
        if member:
            continue
        inv = await db["invitations"].find_one({"family_id": fid}, {"_id": 1})
        if inv:
            continue

        activity = await _family_activity_ts(db, fid, fam) or _dt(fam.get("created_at"))
        if not activity:
            continue

        # warn
        if fam.get("deletion_warned_at") is None and activity <= fam_warn_before:
            owner_id = fam.get("owner_id")
            if owner_id:
                owner = await db["users"].find_one({"_id": owner_id}, {"email": 1})
                if owner and owner.get("email"):
                    send_email(
                        to=owner["email"],
                        subject="FamConn: Unbenutzte Familie wird bald gelöscht",
                        text=(
                            "Hallo,\n\n"
                            f"die Familie „{fam.get('name', '(ohne Name)')}“ wurde angelegt, aber nicht genutzt.\n"
                            "Wenn du sie behalten möchtest, öffne FamConn und lade ein Mitglied ein.\n\n"
                            "Viele Grüße\nFamConn"
                        ),
                    )
            await db["families"].update_one({"_id": fid}, {"$set": {"deletion_warned_at": now}})
            stats["families_warned"] += 1

        # soft delete
        if fam.get("deactivated_at") is None and activity <= fam_soft_before:
            await db["families"].update_one({"_id": fid}, {"$set": {"deactivated_at": now, "is_active": False}})
            stats["families_soft_deleted"] += 1

        # hard delete
        deact = _dt(fam.get("deactivated_at"))
        if deact and deact <= fam_hard_before:
            if stats["families_hard_deleted"] >= MAX_FAM_HARD_DELETES_PER_RUN:
                _log(f"Safety stop: max family hard deletes reached ({MAX_FAM_HARD_DELETES_PER_RUN}).")
                break

            await db["family_members"].delete_many({"family_id": fid})
            await db["invitations"].delete_many({"family_id": fid})
            await db["families"].delete_one({"_id": fid})
            stats["families_hard_deleted"] += 1

    _log("done " + " ".join(f"{k}={v}" for k, v in stats.items()))
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(run_cleanup())
