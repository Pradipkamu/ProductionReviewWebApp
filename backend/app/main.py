from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, SessionLocal, engine
from .migrate import upgrade_database
from .seed import seed_defaults
from .api import actions, auth, dashboard, imports, masters, mis, oee, process, schedules, vendor, analytics, reviews, reports, quality, governance, insights, import_preview, flows

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    upgrade_database()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.attachments_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed_defaults(db)
    import asyncio
    from .services.escalation import refresh_reminders
    async def remind():
        while True:
            try:
                await asyncio.to_thread(run_reminders)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Action reminder refresh failed')
            await asyncio.sleep(60)
    def run_reminders():
        with SessionLocal() as db:
            refresh_reminders(db)
    task = asyncio.create_task(remind())
    try:
        yield
    finally:
        task.cancel()
        from contextlib import suppress
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=settings.app_name, version="0.4.7", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in [auth.router, masters.router, imports.router, schedules.router, mis.router,
               process.router, actions.router, oee.router, dashboard.router, vendor.router, analytics.router, reviews.router, reports.router, quality.router, governance.router, insights.router, import_preview.router, flows.router]:
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name}
