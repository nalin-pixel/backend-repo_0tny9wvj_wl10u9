import os
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from database import db, create_document, get_documents
from bson import ObjectId

app = FastAPI(title="Unity Game Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------
# Helpers
# -----------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change")
TOKEN_EXP_MIN = int(os.getenv("TOKEN_EXP_MIN", "43200"))  # 30 days default


def hash_password(password: str) -> str:
    salt = os.getenv("PWD_SALT", "static-salt")
    return hashlib.sha256((salt + password).encode()).hexdigest()


def create_token(user_id: str) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXP_MIN)).timestamp())
    payload = f"{user_id}:{exp}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_token(token: str) -> Optional[str]:
    try:
        user_id, exp_s, sig = token.split(":")
        payload = f"{user_id}:{exp_s}"
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        if int(exp_s) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return user_id
    except Exception:
        return None


class AuthRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    user: Dict[str, Any]


class SavePayload(BaseModel):
    game_slug: str
    data: Dict[str, Any]


# -----------------
# Base routes
# -----------------
@app.get("/")
def read_root():
    return {"message": "Unity Game Portal Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# -----------------
# Auth routes (simple token auth)
# -----------------
@app.post("/auth/register", response_model=AuthResponse)
def register(payload: AuthRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    existing = db["user"].find_one({"email": str(payload.email).lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    doc = {
        "name": payload.name or payload.email.split("@")[0],
        "email": str(payload.email).lower(),
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "avatar_url": None,
    }
    inserted_id = db["user"].insert_one(doc).inserted_id
    token = create_token(str(inserted_id))
    user = {"_id": str(inserted_id), "name": doc["name"], "email": doc["email"], "avatar_url": None}
    return {"token": token, "user": user}


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: AuthRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    user = db["user"].find_one({"email": str(payload.email).lower()})
    if not user or user.get("password_hash") != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(str(user["_id"]))
    user_out = {"_id": str(user["_id"]), "name": user.get("name"), "email": user.get("email"), "avatar_url": user.get("avatar_url")}
    return {"token": token, "user": user_out}


# Dependency for protected routes
class TokenHeader(BaseModel):
    authorization: str


def get_current_user_id(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    uid = verify_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid


# -----------------
# Games listing (single game for now)
# -----------------
@app.get("/games")
def list_games():
    # For now, return a single game entry. Web and download paths are served by frontend static files.
    return [
        {
            "title": "Tower Defence",
            "slug": "tower-defence",
            "description": "Defend your base against waves of enemies.",
            "cover_image": "/games/tower-defence/cover.jpg",
            "web_path": "/games/tower-defence/index.html",
            "download_path": "/downloads/tower-defence.zip",
        }
    ]


# -----------------
# Saves
# -----------------
@app.get("/saves/{game_slug}")
def get_saves(game_slug: str, authorization: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if authorization:
        user_id = get_current_user_id(authorization)
        save = db["save"].find_one({"user_id": user_id, "game_slug": game_slug})
        if save:
            save["_id"] = str(save["_id"])
            return save
    return {"game_slug": game_slug, "data": {}}


@app.post("/saves")
def upsert_save(payload: SavePayload, authorization: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    user_id = get_current_user_id(authorization)
    now = datetime.now(timezone.utc)
    existing = db["save"].find_one({"user_id": user_id, "game_slug": payload.game_slug})
    if existing:
        db["save"].update_one({"_id": existing["_id"]}, {"$set": {"data": payload.data, "updated_at": now}})
        existing["data"] = payload.data
        existing["updated_at"] = now
        existing["_id"] = str(existing["_id"])
        return existing
    else:
        doc = {"user_id": user_id, "game_slug": payload.game_slug, "data": payload.data, "created_at": now, "updated_at": now}
        inserted_id = db["save"].insert_one(doc).inserted_id
        doc["_id"] = str(inserted_id)
        return doc
