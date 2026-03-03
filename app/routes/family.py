from __future__ import annotations

from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_user
from app.core.utils import generate_invite_code
from app.models.family import (
    FamilyCreate,
    InviteCreate,
    JoinFamily,
    PlaceCreate,
    PlaceOut,
    PlaceUpdate,
)

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

async def _require_member(db, user_id: str, family_id: ObjectId) -> dict:
    m = await db["family_members"].find_one(
        {"family_id": family_id, "user_id": ObjectId(user_id)},
        {"_id": 1, "role": 1},
    )
    if not m:
        raise HTTPException(status_code=403, detail="Not a member of this family")
    return m


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


def _now() -> datetime:
    return datetime.utcnow()


# ---------------- CREATE FAMILY ----------------

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_family(payload: FamilyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Family name required")

    family_doc = {
        "name": name,
        "owner_id": ObjectId(user["id"]),
        "created_at": _now(),
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
        "joined_at": _now(),
    }

    await db["family_members"].insert_one(member_doc)

    invite = await _create_invitation(db, family_id, ObjectId(user["id"]))
    return {"family_id": str(family_id), "invite": invite}


# ---------------- INVITE ----------------

@router.post("/invite")
async def create_invite(payload: InviteCreate, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        family_id = ObjectId(payload.family_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    await _require_owner(db, user["id"], family_id)
    invite = await _create_invitation(db, family_id, ObjectId(user["id"]))
    return {"family_id": payload.family_id, "invite": invite}


# ---------------- JOIN ----------------

@router.post("/join")
async def join_family(payload: JoinFamily, db=Depends(get_db), user=Depends(get_current_user)):
    code = payload.invite_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invite code required")

    now = _now()
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


# ---------------- FAMILY LIST (ME) ----------------

@router.get("/me")
async def my_families(db=Depends(get_db), user=Depends(get_current_user)):
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


# ---------------- PLACES (ORTE/PINS) ----------------

@router.get("/{family_id}/places")
async def list_places(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)
    await _require_member(db, user["id"], fid)

    places = await db["family_places"].find({"family_id": fid}).sort("name", 1).to_list(500)
    out = []
    for p in places:
        out.append({
            "id": str(p["_id"]),
            "family_id": str(p["family_id"]),
            "name": p.get("name", ""),
            "lat": p.get("lat"),
            "lng": p.get("lng"),
            "radius_m": int(p.get("radius_m", 100)),
            "created_by": str(p.get("created_by")) if p.get("created_by") else "",
            "created_at": p.get("created_at").isoformat() + "Z" if p.get("created_at") else "",
            "updated_at": p.get("updated_at").isoformat() + "Z" if p.get("updated_at") else None,
        })
    return {"family_id": family_id, "places": out}


@router.post("/{family_id}/places", status_code=201)
async def create_place(family_id: str, payload: PlaceCreate, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)
    await _require_member(db, user["id"], fid)

    doc = {
        "family_id": fid,
        "name": payload.name.strip(),
        "lat": float(payload.lat),
        "lng": float(payload.lng),
        "radius_m": int(payload.radius_m),
        "created_by": ObjectId(user["id"]),
        "created_at": _now(),
        "updated_at": None,
    }
    res = await db["family_places"].insert_one(doc)
    return {"place": {"id": str(res.inserted_id), **{k: v for k, v in doc.items() if k != "family_id"}, "family_id": str(fid)}}


@router.put("/{family_id}/places/{place_id}")
async def update_place(family_id: str, place_id: str, payload: PlaceUpdate, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)
    await _require_member(db, user["id"], fid)

    try:
        pid = ObjectId(place_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid place_id")

    patch: dict[str, Any] = {"updated_at": _now()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.lat is not None:
        patch["lat"] = float(payload.lat)
    if payload.lng is not None:
        patch["lng"] = float(payload.lng)
    if payload.radius_m is not None:
        patch["radius_m"] = int(payload.radius_m)

    upd = await db["family_places"].update_one({"_id": pid, "family_id": fid}, {"$set": patch})
    if upd.matched_count != 1:
        raise HTTPException(status_code=404, detail="Place not found")

    return {"status": "updated"}


@router.delete("/{family_id}/places/{place_id}")
async def delete_place(family_id: str, place_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    fid = ObjectId(family_id)
    await _require_member(db, user["id"], fid)

    try:
        pid = ObjectId(place_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid place_id")

    res = await db["family_places"].delete_one({"_id": pid, "family_id": fid})
    if res.deleted_count != 1:
        raise HTTPException(status_code=404, detail="Place not found")
    return {"status": "deleted"}


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    # Earth radius in meters
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return r * c


async def derive_status_from_places(db, family_id: ObjectId, lat: float, lng: float) -> str:
    # pick nearest matching place within its radius
    places = await db["family_places"].find({"family_id": family_id}, {"name": 1, "lat": 1, "lng": 1, "radius_m": 1}).to_list(500)
    best_name = None
    best_dist = None
    for p in places:
        plat = float(p.get("lat", 0))
        plng = float(p.get("lng", 0))
        radius = int(p.get("radius_m", 100))
        dist = _haversine_m(lat, lng, plat, plng)
        if dist <= radius:
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_name = (p.get("name") or "").strip() or None
    return best_name or "Unterwegs"
