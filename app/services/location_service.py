
from datetime import datetime, timezone
from math import radians, cos, sin, asin, sqrt

class LocationService:

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c

    @staticmethod
    async def process_location(db, user_id: str, data):
        now = datetime.now(timezone.utc)

        last = await db["locations"].find_one(
            {"user_id": user_id, "family_id": data.family_id},
            sort=[("updated_at", -1)]
        )

        if last:
            distance = LocationService.haversine(
                last["lat"], last["lng"], data.lat, data.lng
            )
            seconds = (now - last["updated_at"]).total_seconds()

            if distance < 100 and seconds < 600:
                return {
                    "status": last.get("status", "unterwegs"),
                    "updated_at": last["updated_at"]
                }

        status = "unterwegs"

        await db["locations"].insert_one({
            "user_id": user_id,
            "family_id": data.family_id,
            "lat": data.lat,
            "lng": data.lng,
            "accuracy": data.accuracy,
            "status": status,
            "updated_at": now
        })

        return {"status": status, "updated_at": now}
