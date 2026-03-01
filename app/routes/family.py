from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.db import get_db
from app.core.utils import generate_invite_code
from app.models.family import FamilyCreate, JoinFamily, InviteCreate
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/family", tags=["Family"])


async def _require_owner(db, user_id: str, family_id: ObjectId) -> None:
    owner = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user_id), "role": "owner"},
        {"_id": 1},
    )
    if not owner:
        raise HTTPException(status_code=403, detail="Owner role required")


async def _create_invitation(db, family_id: ObjectId, created_by: ObjectId) -> dict:
    # Ensure unique code (retry a few times)
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


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_family(payload: FamilyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    """Create a family and add creator as owner. Also returns a first invite (TTL-limited)."""
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

    member_doc = {
        "family_id": family_id,
        "user_id": ObjectId(user["id"]),
        "role": "owner",
        "joined_at": datetime.utcnow(),
    }
    await db["family_members"].insert_one(member_doc)

    invite = await _create_invitation(db, family_id=family_id, created_by=ObjectId(user["id"]))

    return {"family_id": str(family_id), "invite": invite}


@router.post("/invite")
async def create_invite(payload: InviteCreate, db=Depends(get_db), user=Depends(get_current_user)):
    """Create a new, time-limited invite code for a family (owner only)."""
    try:
        family_id = ObjectId(payload.family_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    family = await db["families"].find_one({"_id": family_id}, {"_id": 1})
    if not family:
        raise HTTPException(status_code=404, detail="Family not found")

    await _require_owner(db, user_id=user["id"], family_id=family_id)
    invite = await _create_invitation(db, family_id=family_id, created_by=ObjectId(user["id"]))
    return {"family_id": payload.family_id, "invite": invite}


@router.post("/join")
async def join_family(payload: JoinFamily, db=Depends(get_db), user=Depends(get_current_user)):
    """Join a family by a single-use, time-limited invite code."""
    code = payload.invite_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invite code required")

    now = datetime.utcnow()
    invite = await db["invitations"].find_one({"code": code}, {"_id": 1, "family_id": 1, "expires_at": 1, "used": 1})
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    if invite.get("used"):
        raise HTTPException(status_code=400, detail="Invite already used")

    expires_at = invite.get("expires_at")
    if expires_at and expires_at < now:
        raise HTTPException(status_code=400, detail="Invite expired")

    family_id = invite["family_id"]

    existing = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user["id"])},
        {"_id": 1},
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")

    # Mark invite as used first (best-effort guard against race conditions)
    updated = await db["invitations"].update_one(
        {"_id": invite["_id"], "used": False},
        {"$set": {"used": True, "used_at": now, "used_by": ObjectId(user["id"])}},
    )
    if updated.modified_count != 1:
        raise HTTPException(status_code=400, detail="Invite already used")

    member_doc = {
        "family_id": family_id,
        "user_id": ObjectId(user["id"]),
        "role": "member",
        "joined_at": now,
    }
    await db["family_members"].insert_one(member_doc)

    return {"message": "Joined successfully"}


@router.get("/me")
async def my_families(db=Depends(get_db), user=Depends(get_current_user)):
    """List families the current user is a member of."""
    cursor = db["family_members"].find({"user_id": ObjectId(user["id"])})
    memberships = await cursor.to_list(length=200)

    if not memberships:
        return {"families": []}

    family_ids = [m["family_id"] for m in memberships]
    fam_cursor = db["families"].find({"_id": {"$in": family_ids}})
    families = await fam_cursor.to_list(length=200)

    fam_map = {str(f["_id"]): f for f in families}
    out = []
    for m in memberships:
        fid = str(m["family_id"])
        f = fam_map.get(fid)
        if not f:
            continue
        out.append({
            "id": fid,
            "name": f.get("name", ""),
            "role": m.get("role", "member"),
        })
    return {"families": out}
