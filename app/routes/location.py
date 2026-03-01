
from fastapi import APIRouter, Depends
from app.models.location_models import LocationUpdate, LocationResponse
from app.core.security import get_current_user
from app.core.db import get_db
from app.services.location_service import LocationService

router = APIRouter(prefix="/api/v1/location", tags=["Location"])

@router.post("/update", response_model=LocationResponse)
async def update_location(
    payload: LocationUpdate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    result = await LocationService.process_location(db, user["id"], payload)
    return result
