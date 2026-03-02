from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.db import get_db
from app.core.utils import generate_invite_code
from app.models.family import FamilyCreate, JoinFamily, InviteCreate
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/family", tags=["Family"])


# ---------------- DISPLAY NAME LOGIC ----------------

async def _pick_unique_display_name(db, family_id, base_name: str) -> str:
    base = (base_name or "").strip()
    if not base:
        base = "Mitglied"

    existing = await db["family_members"].find(
        {"family_id": family_id, "display_name": {"$regex": f"^{base}(?: [0-9]+)?$"}},
        {"display_name": 1},
    ).to_list(length=500)

    if not existing:
        return base

    used_nums = set()
    for m in existing:
        dn = (m.get("display_name") or "").strip()
        if dn == base:
            used_nums.add(1)
        elif dn.startswith(base + " "):
            tail = dn[len(base) + 1 :]
            if tail.isdigit():
                used_nums.add(int(tail))

    n = 2
    while n in used_nums:
        n += 1
    return f"{base} {n}"


# ---------------- INTERNAL HELPERS ----------------

async def _require_owner(db, user_id: str, family_id: ObjectId) -> None:
    owner = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user_id), "role": "owner"},
        {"_id": 1},
    )
    if not owner:
        raise HTTPException(status_code=403, detail="Owner role required")


async def _create_invitation(db, family_id: ObjectId, created_by: ObjectId) -> dict:
    code = None
    for _ in range(8):
        candidate = generate_invite_code()
        exists = await db["invitations"].find_one({"code": candidate}, {"_id": 1})
        if not exists:
            code = candidate
            break
    if not code:
        raise HTTPException(status_code=500, detail="Could not generate invite code")

    expires_at = datetime.utcnow() + timedelta(minutes=settings.INVITE_TTL_MINUTES)

    doc = {
        "family_id": family_id,
        "code": code,
        "expires_at": expires_at,
        "used": False,
        "created_by": created_by,
        "created_at": datetime.utcnow(),
    }

    await db["invitations"].insert_one(doc)
    return {"code": code, "expires_at": expires_at.isoformat() + "Z"}


# ---------------- CREATE FAMILY ----------------

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_family(payload: FamilyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Family name required")

    family_doc = {
        "name": name,
        "owner_id": ObjectId(user["id"]),
        "created_at": datetime.utcnow(),
    }

    result = await db["families"].insert_one(family_doc)
    family_id = result.inserted_id

    # Fetch user for display name
    u = await db["users"].find_one({"_id": ObjectId(user["id"])}, {"first_name": 1, "email": 1})
    base = (u or {}).get("first_name") or ((u or {}).get("email") or "").split("@")[0]
    display_name = await _pick_unique_display_name(db, family_id, base)

    member_doc = {
        "family_id": family_id,
        "user_id": ObjectId(user["id"]),
        "role": "owner",
        "display_name": display_name,
        "sharing_enabled": True,
        "joined_at": datetime.utcnow(),
    }

    await db["family_members"].insert_one(member_doc)

    invite = await _create_invitation(db, family_id, ObjectId(user["id"]))
    return {"family_id": str(family_id), "invite": invite}


# ---------------- INVITE ----------------

@router.post("/invite")
async def create_invite(payload: InviteCreate, db=Depends(get_db), user=Depends(get_current_user)):
    family_id = ObjectId(payload.family_id)

    await _require_owner(db, user["id"], family_id)
    invite = await _create_invitation(db, family_id, ObjectId(user["id"]))
    return {"family_id": payload.family_id, "invite": invite}


# ---------------- JOIN ----------------

@router.post("/join")
async def join_family(payload: JoinFamily, db=Depends(get_db), user=Depends(get_current_user)):
    code = payload.invite_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invite code required")

    now = datetime.utcnow()
    invite = await db["invitations"].find_one({"code": code})
    if not invite or invite.get("used"):
        raise HTTPException(status_code=400, detail="Invalid invite")

    if invite.get("expires_at") and invite["expires_at"] < now:
        raise HTTPException(status_code=400, detail="Invite expired")

    family_id = invite["family_id"]

    existing = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user["id"])}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")

    await db["invitations"].update_one(
        {"_id": invite["_id"]},
        {"$set": {"used": True, "used_at": now}},
    )

    u = await db["users"].find_one({"_id": ObjectId(user["id"])}, {"first_name": 1, "email": 1})
    base = (u or {}).get("first_name") or ((u or {}).get("email") or "").split("@")[0]
    display_name = await _pick_unique_display_name(db, family_id, base)

    member_doc = {
        "family_id": family_id,
        "user_id": ObjectId(user["id"]),
        "role": "member",
        "display_name": display_name,
        "sharing_enabled": True,
        "joined_at": now,
    }

    await db["family_members"].insert_one(member_doc)
    return {"message": "Joined successfully"}


# ---------------- SHARING CONTROL ----------------

@router.post("/{family_id}/sharing/enable")
async def enable_sharing(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)

    await db["family_members"].update_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"$set": {"sharing_enabled": True}},
    )

    return {"status": "sharing_enabled"}


@router.post("/{family_id}/sharing/disable")
async def disable_sharing(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)

    await db["family_members"].update_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"$set": {"sharing_enabled": False}},
    )

    return {"status": "sharing_disabled"}


# ---------------- MEMBERS ----------------

@router.get("/{family_id}/members")
async def family_members(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)

    membership = await db["family_members"].find_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])}
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member")

    members = await db["family_members"].find({"family_id": fid}).to_list(500)

    out = []
    for m in members:
        out.append({
            "user_id": str(m["user_id"]),
            "display_name": m.get("display_name"),
            "role": m.get("role"),
            "sharing_enabled": m.get("sharing_enabled", True),
            "joined_at": m.get("joined_at").isoformat() + "Z",
        })

    return {"family_id": family_id, "members": out}