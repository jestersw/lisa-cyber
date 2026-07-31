from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.endpoints import (
    agents,
    applications,
    events,
    generate,
    heartbeat,
    ml,
    roles,
    templates,
)
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

app.include_router(roles.router, prefix="/api", tags=["Roles"])
app.include_router(templates.router, prefix="/api", tags=["Behavior templates"])
app.include_router(applications.router, prefix="/api", tags=["Application templates"])
app.include_router(agents.router, prefix="/api", tags=["Agents"])
app.include_router(heartbeat.router, prefix="/api", tags=["Heartbeat"])
app.include_router(events.router, prefix="/api", tags=["Activity events"])
app.include_router(generate.router, prefix="/api", tags=["Template generation"])
app.include_router(ml.router, prefix="/api", tags=["ML inference"])


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
