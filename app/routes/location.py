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

    # must be member AND sharing enabled
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

    # Upsert last location per user+family
    await db["locations"].update_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"$set": doc},
        upsert=True,
    )

    return {"status": "ok", "derived_status": derived_status}
