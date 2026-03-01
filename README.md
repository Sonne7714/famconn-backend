# FamConn Backend (FastAPI + MongoDB Atlas + Argon2)

This backend is designed to be:
- **Render-ready** (listens on `$PORT`)
- **Mobile-friendly auth** (JWT access + rotating refresh token)
- **Async** (Motor)

## Local setup (Windows / Linux / macOS)

1) Create venv and install deps

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

pip install -r requirements.txt
```

2) Create `.env`

Copy `.env.example` to `.env` and set at least `MONGO_URI`.

3) Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:
- http://localhost:8000/docs

## Render start command

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## API

Base: `/api/v1`

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET  /api/v1/auth/me`
- `GET  /health`

## Family (Invitations)

- POST `/api/v1/family/create` (auth required) -> returns first invite
- POST `/api/v1/family/invite` (auth required, owner) -> create new 30-min single-use invite
- POST `/api/v1/family/join` (auth required) -> join via invite code
- GET `/api/v1/family/me` (auth required)
