from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.db import connect_to_mongo, close_mongo_connection
from app.routes.auth import router as auth_router
from app.routes import family


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        # Sensible default headers for APIs
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # If you later serve HTML, consider a CSP. For pure JSON API we keep it simple.
        return response


app = FastAPI(
    title="FamConn API",
    version="1.0.0",
)

app.add_middleware(SecurityHeadersMiddleware)

# CORS (mainly for future web tooling; React Native isn't restricted the same way,
# but keeping it here helps for web admin/app)
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def _startup():
    # Basic safety check for production
    if settings.ENV.lower() == "production" and settings.JWT_SECRET in ("CHANGE_ME", "", None):
        raise RuntimeError("JWT_SECRET is not set. Configure a strong secret in your environment.")

    await connect_to_mongo()


@app.on_event("shutdown")
async def _shutdown():
    await close_mongo_connection()


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.ENV}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(family.router)