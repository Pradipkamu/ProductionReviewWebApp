"""Best-effort Firebase Cloud Messaging delivery for employee chat."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from sqlalchemy import select

from ..db import SessionLocal
from ..models import ChatDeviceToken

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _firebase_app():
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not credentials_path or not os.path.isfile(credentials_path):
        logger.info("Firebase messaging is disabled: service-account file is unavailable")
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials
        try:
            return firebase_admin.get_app()
        except ValueError:
            return firebase_admin.initialize_app(credentials.Certificate(credentials_path))
    except Exception:
        logger.exception("Firebase Admin initialization failed; chat push is disabled")
        return None


def send_chat_push(user_ids: list[int], conversation_id: int, sender_name: str) -> None:
    """Send generic chat alerts; never include message content or fail chat delivery."""
    if not user_ids:
        return
    app = _firebase_app()
    if app is None:
        return
    try:
        from firebase_admin import messaging
        with SessionLocal() as db:
            rows = db.scalars(select(ChatDeviceToken).where(
                ChatDeviceToken.user_id.in_(set(user_ids)),
                ChatDeviceToken.is_active.is_(True),
            )).all()
            for row in rows:
                try:
                    message = messaging.Message(
                        notification=messaging.Notification(
                            title="New Production Review message",
                            body=f"New message from {sender_name}",
                        ),
                        data={"type": "chat_message", "conversation_id": str(conversation_id)},
                        token=row.token,
                        android=messaging.AndroidConfig(priority="high"),
                    )
                    messaging.send(message, app=app)
                except Exception as exc:
                    code = getattr(getattr(exc, "code", None), "name", "")
                    if code in {"UNREGISTERED", "INVALID_ARGUMENT"}:
                        row.is_active = False
                        db.commit()
                    logger.warning("Chat push delivery failed for a registered device (%s)", code or type(exc).__name__)
    except Exception:
        logger.exception("Chat push delivery batch failed")
