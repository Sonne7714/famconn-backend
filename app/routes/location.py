from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import get_current_user
from app.routes.family import derive_status_from_places

router = APIRouter(prefix="/api/v1/location", tags=["Location"])


def _now() -> datetime:
    return datetime.utcnow()


def _status_label(value: str | None) -> str:
    text = (value or "").strip()
    return text or "Unterwegs"


def _is_place_status(value: str | None) -> bool:
    return _status_label(value) != "Unterwegs"


async def _create_location_transition_events(
    db,
    *,
    family_id: ObjectId,
    user_id: ObjectId,
    display_name: str,
    previous_status: str | None,
    next_status: str | None,
    lat: float,
    lng: float,
    source: str,
    accuracy_m: float | None,
    occurred_at: datetime,
) -> list[dict[str, Any]]:
    prev = _status_label(previous_status)
    curr = _status_label(next_status)

    # Beim allerersten Standort keine Events erzeugen
    if previous_status is None:
        return []

    if prev == curr:
        return []

    docs: list[dict[str, Any]] = []

    # Ort verlassen
    if _is_place_status(prev) and curr == "Unterwegs":
        docs.append(
            {
                "family_id": family_id,
                "user_id": user_id,
                "display_name": display_name,
                "event_type": "left_place",
                "place_name": prev,
                "from_status": prev,
                "to_status": curr,
                "lat": lat,
                "lng": lng,
                "accuracy_m": accuracy_m,
                "source": source,
                "occurred_at": occurred_at,
                "created_at": occurred_at,
            }
        )

    # Ort betreten
    elif prev == "Unterwegs" and _is_place_status(curr):
        docs.append(
            {
                "family_id": family_id,
                "user_id": user_id,
                "display_name": display_name,
                "event_type": "entered_place",
                "place_name": curr,
                "from_status": prev,
                "to_status": curr,
                "lat": lat,
                "lng": lng,
                "accuracy_m": accuracy_m,
                "source": source,
                "occurred_at": occurred_at,
                "created_at": occurred_at,
            }
        )

    # Direkter Wechsel von Ort A nach Ort B
    elif _is_place_status(prev) and _is_place_status(curr) and prev != curr:
        docs.append(
            {
                "family_id": family_id,
                "user_id": user_id,
                "display_name": display_name,
                "event_type": "left_place",
                "place_name": prev,
                "from_status": prev,
                "to_status": curr,
                "lat": lat,
                "lng": lng,
                "accuracy_m": accuracy_m,
                "source": source,
                "occurred_at": occurred_at,
                "created_at": occurred_at,
            }
        )
        docs.append(
            {
                "family_id": family_id,
                "user_id": user_id,
                "display_name": display_name,
                "event_type": "entered_place",
                "place_name": curr,
                "from_status": prev,
                "to_status": curr,
                "lat": lat,
                "lng": lng,
                "accuracy_m": accuracy_m,
                "source": source,
                "occurred_at": occurred_at,
                "created_at": occurred_at,
            }
        )

    if docs:
        await db["location_events"].insert_many(docs)

    return docs


@router.post("/update")
async def update_location(payload: dict, db=Depends(get_db), user=Depends(get_current_user)):
    """Receives location updates from clients.

    Expected payload:
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
        {"_id": 1, "sharing_enabled": 1, "display_name": 1},
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
    now = _now()

    previous_location = await db["locations"].find_one(
        {"family_id": fid, "user_id": ObjectId(user["id"])},
        {"derived_status": 1},
    )
    previous_status = previous_location.get("derived_status") if previous_location else None

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

    created_events = await _create_location_transition_events(
        db,
        family_id=fid,
        user_id=ObjectId(user["id"]),
        display_name=(membership.get("display_name") or "Mitglied"),
        previous_status=previous_status,
        next_status=derived_status,
        lat=lat,
        lng=lng,
        source=source,
        accuracy_m=accuracy_m,
        occurred_at=now,
    )

    return {
        "status": "ok",
        "derived_status": derived_status,
        "events_created": len(created_events),
    }


@router.get("/family/{family_id}/members")
async def get_family_member_locations(
    family_id: str,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
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


@router.get("/family/{family_id}/events")
async def get_family_location_events(
    family_id: str,
    limit: int = 50,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
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

    safe_limit = max(1, min(int(limit or 50), 100))

    events = await db["location_events"].find(
        {"family_id": fid},
        {
            "user_id": 1,
            "display_name": 1,
            "event_type": 1,
            "place_name": 1,
            "from_status": 1,
            "to_status": 1,
            "lat": 1,
            "lng": 1,
            "accuracy_m": 1,
            "source": 1,
            "occurred_at": 1,
        },
    ).sort("occurred_at", -1).to_list(length=safe_limit)

    out = []
    for ev in events:
        occurred_at = ev.get("occurred_at")
        out.append(
            {
                "user_id": str(ev.get("user_id")) if ev.get("user_id") else "",
                "display_name": ev.get("display_name") or "Mitglied",
                "event_type": ev.get("event_type") or "",
                "place_name": ev.get("place_name"),
                "from_status": ev.get("from_status"),
                "to_status": ev.get("to_status"),
                "lat": ev.get("lat"),
                "lng": ev.get("lng"),
                "accuracy_m": ev.get("accuracy_m"),
                "source": ev.get("source"),
                "occurred_at": occurred_at.isoformat() + "Z" if occurred_at else None,
            }
        )

    return {"family_id": family_id, "events": out}