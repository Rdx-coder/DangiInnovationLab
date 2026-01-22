from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
from datetime import datetime, timezone
import uuid
import os
import logging
from contextlib import asynccontextmanager

# --------------------------------------------------
# ENV SETUP
# --------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

if not MONGO_URL or not DB_NAME:
    raise RuntimeError("❌ MONGO_URL or DB_NAME not set in .env")

# --------------------------------------------------
# LOGGING
# --------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app")

# --------------------------------------------------
# DATABASE LIFESPAN (MODERN WAY)
# --------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    try:
        await db.command("ping")
        logger.info("✅ MongoDB connected successfully")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        raise

    app.state.mongo_client = client
    app.state.db = db

    yield

    client.close()
    logger.info("🔌 MongoDB connection closed")

# --------------------------------------------------
# APP INIT
# --------------------------------------------------
app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

# --------------------------------------------------
# MODELS
# --------------------------------------------------
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str

# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.get("/db-health")
async def db_health():
    try:
        await app.state.db.command("ping")
        return {"database": "connected"}
    except Exception as e:
        return {"database": "disconnected", "error": str(e)}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(payload: StatusCheckCreate):
    status = StatusCheck(client_name=payload.client_name)

    doc = status.model_dump()
    doc["timestamp"] = doc["timestamp"].isoformat()

    await app.state.db.status_checks.insert_one(doc)
    return status

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    docs = await app.state.db.status_checks.find({}, {"_id": 0}).to_list(1000)

    for d in docs:
        if isinstance(d.get("timestamp"), str):
            d["timestamp"] = datetime.fromisoformat(d["timestamp"])

    return docs

# --------------------------------------------------
# MIDDLEWARE & ROUTER
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
