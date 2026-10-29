from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .auth import request_is_https
from . import __version__
from .db import Base, SessionLocal, engine
from .migrate import upgrade_database
from .seed import seed_defaults
from .api import actions, auth, dashboard, imports, masters, mis, oee, process, schedules, vendor, analytics, reviews, reports, quality, quality_salvage, governance, insights, import_preview, flows, diagnostics, capacity, special_quality

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
    def close_inactive_meetings():
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from .models import ReviewSession, UserSession
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=30)
        with SessionLocal() as db:
            # Lock rows while evaluating so concurrent app workers cannot close a MOM twice.
            rows = db.scalars(select(ReviewSession).where(ReviewSession.ended_at.is_(None),
                ReviewSession.owner_id.is_not(None)).with_for_update(skip_locked=True)).all()
            changed = False
            for meeting in rows:
                owner_active = db.scalar(select(UserSession.id).where(UserSession.user_id == meeting.owner_id,
                    UserSession.revoked_at.is_(None), UserSession.expires_at > now,
                    UserSession.last_seen_at > cutoff).limit(1))
                if not owner_active:
                    meeting.ended_at = now
                    meeting.auto_close_reason = 'Automatically closed due to owner inactivity for more than 30 minutes.'
                    changed = True
            if changed:
                db.commit()
    async def maintain_meetings():
        while True:
            try:
                await asyncio.to_thread(close_inactive_meetings)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Meeting inactivity sweep failed')
            await asyncio.sleep(60)
    task = asyncio.create_task(remind())
    meeting_task = asyncio.create_task(maintain_meetings())
    try:
        yield
    finally:
        task.cancel()
        meeting_task.cancel()
        from contextlib import suppress
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await meeting_task


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    docs_url=None if settings.environment.lower() == "production" else "/docs",
    redoc_url=None if settings.environment.lower() == "production" else "/redoc",
    openapi_url=None if settings.environment.lower() == "production" else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    secure = request_is_https(request)
    if settings.require_https and not secure and request.url.path != "/api/health":
        return JSONResponse(
            status_code=426,
            content={"detail": "HTTPS is required by server policy"},
            headers={"Upgrade": "TLS/1.2, HTTP/1.1"},
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/auth/"):
        response.headers["Cache-Control"] = "no-store"
    if secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

for router in [auth.router, masters.router, imports.router, schedules.router, mis.router,
               process.router, actions.router, oee.router, dashboard.router, vendor.router, analytics.router, reviews.router, reports.router, quality.router, quality_salvage.router, special_quality.router, governance.router, insights.router, import_preview.router, flows.router, diagnostics.router, capacity.router]:
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name, "version": __version__}
