from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.db import get_db
from app.core.utils import generate_invite_code
from app.models.family import FamilyCreate, JoinFamily, InviteCreate, MemberRoleUpdate, TransferOwner
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/family", tags=["Family"])


def _utcnow() -> datetime:
    return datetime.utcnow()


async def _require_member(db, user_id: str, family_id: ObjectId) -> dict:
    m = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user_id)},
        {"_id": 0, "role": 1, "joined_at": 1},
    )
    if not m:
        raise HTTPException(status_code=403, detail="Not a family member")
    m["role"] = m.get("role") or "member"
    return m


async def _require_owner(db, user_id: str, family_id: ObjectId) -> None:
    owner = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user_id), "role": "owner"},
        {"_id": 1},
    )
    if not owner:
        raise HTTPException(status_code=403, detail="Owner role required")


async def _require_owner_or_admin(db, user_id: str, family_id: ObjectId) -> str:
    m = await _require_member(db, user_id=user_id, family_id=family_id)
    role = m.get("role", "member")
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return role


async def _create_invitation(db, family_id: ObjectId, created_by: ObjectId, ttl_minutes: int | None = None) -> dict:
    # Ensure unique code (retry a few times)
    code = None
    for _ in range(10):
        candidate = generate_invite_code()
        exists = await db["invitations"].find_one({"code": candidate}, {"_id": 1})
        if not exists:
            code = candidate
            break
    if not code:
        raise HTTPException(status_code=500, detail="Could not generate invite code")

    ttl = ttl_minutes if ttl_minutes is not None else settings.INVITE_TTL_MINUTES
    expires_at = _utcnow() + timedelta(minutes=int(ttl))

    doc = {
        "family_id": family_id,
        "code": code,
        "expires_at": expires_at,
        "used": False,
        "created_by": created_by,
        "created_at": _utcnow(),
    }
    try:
        await db["invitations"].insert_one(doc)
    except Exception:
        # In rare races with unique index, retry once
        candidate = generate_invite_code()
        doc["code"] = candidate
        await db["invitations"].insert_one(doc)

    return {"code": doc["code"], "expires_at": expires_at.isoformat() + "Z"}


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_family(payload: FamilyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    """Create a family and add creator as owner. Also returns a first invite (TTL-limited)."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Family name required")

    family_doc = {
        "name": name,
        "owner_id": ObjectId(user["id"]),
        "created_at": _utcnow(),
    }

    result = await db["families"].insert_one(family_doc)
    family_id = result.inserted_id

    member_doc = {
        "family_id": family_id,
        "user_id": ObjectId(user["id"]),
        "role": "owner",
        "joined_at": _utcnow(),
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
    invite = await _create_invitation(
        db,
        family_id=family_id,
        created_by=ObjectId(user["id"]),
        ttl_minutes=payload.ttl_minutes,
    )
    return {"family_id": payload.family_id, "invite": invite}


@router.post("/join")
async def join_family(payload: JoinFamily, db=Depends(get_db), user=Depends(get_current_user)):
    """Join a family by a single-use, time-limited invite code."""
    code = payload.invite_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invite code required")

    now = _utcnow()
    invite = await db["invitations"].find_one(
        {"code": code},
        {"_id": 1, "family_id": 1, "expires_at": 1, "used": 1},
    )
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
        out.append(
            {
                "id": fid,
                "name": f.get("name", ""),
                "role": (m.get("role") or "member"),
            }
        )
    return {"families": out}


# ==========================================================
# Step 2: Members
# ==========================================================
@router.get("/{family_id}/members")
async def list_members(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        fid = ObjectId(family_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    await _require_member(db, user_id=user["id"], family_id=fid)

    members = await db["family_members"].find({"family_id": fid}).to_list(length=500)
    user_ids = [m["user_id"] for m in members]

    users = await db["users"].find({"_id": {"$in": user_ids}}, {"email": 1}).to_list(length=500)
    email_map = {u["_id"]: u.get("email", "") for u in users}

    out = []
    for m in members:
        out.append(
            {
                "user_id": str(m["user_id"]),
                "email": email_map.get(m["user_id"], ""),
                "role": (m.get("role") or "member"),
                "joined_at": (m.get("joined_at").isoformat() + "Z") if m.get("joined_at") else None,
            }
        )

    # Stable ordering: owner first, then admin, then member; then email
    order = {"owner": 0, "admin": 1, "member": 2}
    out.sort(key=lambda x: (order.get(x["role"], 9), x.get("email") or ""))
    return {"family_id": family_id, "members": out}


@router.patch("/{family_id}/members/{user_id}")
async def update_member_role(
    family_id: str,
    user_id: str,
    payload: MemberRoleUpdate,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        fid = ObjectId(family_id)
        uid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    await _require_owner(db, user_id=user["id"], family_id=fid)

    target = await db["family_members"].find_one({"family_id": fid, "user_id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if (target.get("role") or "member") == "owner":
        raise HTTPException(status_code=400, detail="Use transfer-owner to change owner")

    await db["family_members"].update_one(
        {"family_id": fid, "user_id": uid},
        {"$set": {"role": payload.role}},
    )
    return {"message": "Role updated"}


@router.delete("/{family_id}/members/{user_id}")
async def remove_member(
    family_id: str,
    user_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        fid = ObjectId(family_id)
        uid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    acting_role = await _require_owner_or_admin(db, user_id=user["id"], family_id=fid)

    target = await db["family_members"].find_one({"family_id": fid, "user_id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if (target.get("role") or "member") == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot be removed")

    # Admin cannot remove owner already handled; allow removing admins/members
    await db["family_members"].delete_one({"family_id": fid, "user_id": uid})
    return {"message": "Member removed"}


# ==========================================================
# Step 3: Invites management
# ==========================================================
@router.get("/{family_id}/invites")
async def list_invites(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        fid = ObjectId(family_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    await _require_member(db, user_id=user["id"], family_id=fid)

    now = _utcnow()
    invites = await db["invitations"].find(
        {"family_id": fid, "used": False, "expires_at": {"$gt": now}},
        {"code": 1, "expires_at": 1, "created_at": 1},
    ).to_list(length=200)

    out = []
    for inv in invites:
        out.append(
            {
                "id": str(inv["_id"]),
                "code": inv.get("code", ""),
                "expires_at": (inv["expires_at"].isoformat() + "Z") if inv.get("expires_at") else None,
                "created_at": (inv["created_at"].isoformat() + "Z") if inv.get("created_at") else None,
            }
        )
    out.sort(key=lambda x: x.get("expires_at") or "")
    return {"family_id": family_id, "invites": out}


@router.delete("/{family_id}/invites/{invite_id}")
async def revoke_invite(
    family_id: str,
    invite_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        fid = ObjectId(family_id)
        iid = ObjectId(invite_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    await _require_owner(db, user_id=user["id"], family_id=fid)

    res = await db["invitations"].delete_one({"_id": iid, "family_id": fid, "used": False})
    if res.deleted_count != 1:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"message": "Invite revoked"}


# ==========================================================
# Owner transfer
# ==========================================================
@router.post("/{family_id}/transfer-owner")
async def transfer_owner(
    family_id: str,
    payload: TransferOwner,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        fid = ObjectId(family_id)
        new_owner_id = ObjectId(payload.new_owner_user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    await _require_owner(db, user_id=user["id"], family_id=fid)

    if str(new_owner_id) == user["id"]:
        raise HTTPException(status_code=400, detail="Already owner")

    # Ensure new owner is a member
    new_owner_member = await db["family_members"].find_one({"family_id": fid, "user_id": new_owner_id})
    if not new_owner_member:
        raise HTTPException(status_code=404, detail="Target user is not a member")

    # Update family document
    await db["families"].update_one({"_id": fid}, {"$set": {"owner_id": new_owner_id}})

    # Swap roles
    await db["family_members"].update_one(
        {"family_id": fid, "user_id": ObjectId(user["id"]), "role": "owner"},
        {"$set": {"role": "member"}},
    )
    await db["family_members"].update_one(
        {"family_id": fid, "user_id": new_owner_id},
        {"$set": {"role": "owner"}},
    )

    return {"message": "Owner transferred", "new_owner_user_id": str(new_owner_id)}
