from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, SessionLocal, engine
from .migrations import ensure_compatibility_columns
from .seed import seed_defaults
from .api import actions, auth, dashboard, imports, masters, mis, oee, process, schedules, vendor, analytics, reviews, reports, quality

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_compatibility_columns(engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.attachments_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed_defaults(db)
    yield


app = FastAPI(title=settings.app_name, version="0.2.8", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in [auth.router, masters.router, imports.router, schedules.router, mis.router,
               process.router, actions.router, oee.router, dashboard.router, vendor.router, analytics.router, reviews.router, reports.router, quality.router]:
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name}
