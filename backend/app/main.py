from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from app import database

    if database._engine is not None:
        database._engine.dispose()


settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running", "docs": "/docs"}


@app.get("/api/health")
def health() -> dict[str, str]:
    database_status = "down"
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        database_status = "up"
    except Exception:
        database_status = "down"
    return {
        "status": "healthy" if database_status == "up" else "degraded",
        "database": database_status,
    }
