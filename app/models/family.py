from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, conint, confloat


class FamilyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class JoinFamily(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=64)


class InviteCreate(BaseModel):
    family_id: str = Field(..., min_length=1, max_length=64)


# ---- Places (Orte/Pins) ----

class PlaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    lat: confloat(ge=-90, le=90)  # type: ignore
    lng: confloat(ge=-180, le=180)  # type: ignore
    radius_m: conint(ge=50, le=2000) = 100  # default 100m


class PlaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    lat: Optional[confloat(ge=-90, le=90)] = None  # type: ignore
    lng: Optional[confloat(ge=-180, le=180)] = None  # type: ignore
    radius_m: Optional[conint(ge=50, le=2000)] = None


class PlaceOut(BaseModel):
    id: str
    family_id: str
    name: str
    lat: float
    lng: float
    radius_m: int
    created_by: str
    created_at: str
    updated_at: Optional[str] = None
