from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import get_current_user
from app.routes.family import derive_status_from_places

router = APIRouter(prefix="/api/v1/location", tags=["Location"])


@router.post("/update")
async def update_location(payload: dict, db=Depends(get_db), user=Depends(get_current_user)):
    """Receives location updates from clients.

    Expected payload (mobile sends):
    - family_id: str
    - lat: float
    - lng: float
    - accuracy_m: float | int | None
    - source: 'bg' | 'fg' | 'manual' | ...
    """
    family_id = payload.get("family_id")
    if not family_id:
        raise HTTPException(status_code=400, detail="family_id required")
    try:
        fid = ObjectId(str(family_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    membership = await db["family_members"].find_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"_id": 1, "sharing_enabled": 1},
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this family")
    if membership.get("sharing_enabled") is False:
        return {"status": "sharing_disabled"}

    try:
        lat = float(payload.get("lat"))
        lng = float(payload.get("lng"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lat/lng")

    accuracy = payload.get("accuracy_m")
    try:
        accuracy_m = float(accuracy) if accuracy is not None else None
    except Exception:
        accuracy_m = None

    source = str(payload.get("source") or "unknown")
    now = datetime.utcnow()

    derived_status = await derive_status_from_places(db, fid, lat, lng)

    doc = {
        "family_id": fid,
        "user_id": ObjectId(user["id"]),
        "lat": lat,
        "lng": lng,
        "accuracy_m": accuracy_m,
        "source": source,
        "derived_status": derived_status,
        "status_source": "geofence",
        "created_at": now,
    }

    await db["locations"].update_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"$set": doc},
        upsert=True,
    )

    return {"status": "ok", "derived_status": derived_status}


@router.get("/family/{family_id}/members")
async def get_family_member_locations(family_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        fid = ObjectId(family_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid family_id")

    membership = await db["family_members"].find_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"_id": 1},
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this family")

    family_members = await db["family_members"].find(
        {"family_id": fid},
        {"user_id": 1, "display_name": 1, "role": 1, "sharing_enabled": 1},
    ).to_list(length=500)

    user_ids = [m["user_id"] for m in family_members]
    locations = await db["locations"].find(
        {"family_id": fid, "user_id": {"$in": user_ids}},
        {
            "user_id": 1,
            "lat": 1,
            "lng": 1,
            "accuracy_m": 1,
            "source": 1,
            "derived_status": 1,
            "created_at": 1,
        },
    ).to_list(length=500)

    loc_map = {str(loc["user_id"]): loc for loc in locations}

    out = []
    for m in family_members:
        uid = str(m["user_id"])
        loc = loc_map.get(uid)

        item = {
            "user_id": uid,
            "display_name": m.get("display_name") or "Mitglied",
            "role": m.get("role") or "member",
            "sharing_enabled": m.get("sharing_enabled", True),
            "has_location": loc is not None,
        }

        if loc:
            lat = loc.get("lat")
            lng = loc.get("lng")

            recalculated_status = None
            if lat is not None and lng is not None:
                try:
                    recalculated_status = await derive_status_from_places(
                        db,
                        fid,
                        float(lat),
                        float(lng),
                    )
                except Exception:
                    recalculated_status = loc.get("derived_status") or "Unterwegs"
            else:
                recalculated_status = loc.get("derived_status") or "Unterwegs"

            stored_status = loc.get("derived_status")
            if recalculated_status != stored_status:
                await db["locations"].update_one(
                    {"family_id": fid, "user_id": ObjectId(uid)},
                    {
                        "$set": {
                            "derived_status": recalculated_status,
                            "status_source": "geofence",
                        }
                    },
                )

            item.update(
                {
                    "lat": lat,
                    "lng": lng,
                    "accuracy_m": loc.get("accuracy_m"),
                    "source": loc.get("source"),
                    "derived_status": recalculated_status,
                    "updated_at": loc.get("created_at").isoformat() + "Z"
                    if loc.get("created_at")
                    else None,
                }
            )

        out.append(item)

    out.sort(key=lambda x: (x.get("display_name") or "").lower())
    return {"family_id": family_id, "members": out}