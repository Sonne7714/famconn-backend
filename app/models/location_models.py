
from pydantic import BaseModel
from datetime import datetime

class LocationUpdate(BaseModel):
    family_id: str
    lat: float
    lng: float
    accuracy: float

class LocationResponse(BaseModel):
    status: str
    updated_at: datetime
