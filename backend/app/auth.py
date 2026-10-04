"""Authentication and security-audit helpers shared by API modules.

Keep the exported security-event recorder in this module because update
packages and API modules use it as a deployment compatibility contract.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import SecurityEvent, User, UserSession

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

__all__ = [
    "client_ip",
    "create_access_token",
    "create_session",
    "get_current_user",
    "hash_password",
    "record_security_event",
    "request_is_https",
    "revoke_user_sessions",
    "verify_password",
]


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return "pbkdf2_sha256$210000$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def client_ip(request: Request) -> str | None:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:80]
    return request.client.host[:80] if request.client and request.client.host else None


def request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if settings.trust_proxy_headers:
        return request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    return False


def record_security_event(
    db: Session,
    request: Request,
    event_type: str,
    *,
    success: bool,
    user: User | None = None,
    username: str | None = None,
    detail: str | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        event_type=event_type,
        success=success,
        user_id=user.id if user else None,
        username=(user.username if user else username),
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        detail=detail,
    )
    db.add(event)
    return event


def create_session(db: Session, user: User, request: Request) -> UserSession:
    now = datetime.utcnow()
    row = UserSession(
        session_id=secrets.token_urlsafe(36),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.access_token_expire_minutes),
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    db.add(row)
    db.flush()
    return row


def revoke_user_sessions(db: Session, user_id: int, *, except_session_id: str | None = None) -> int:
    now = datetime.utcnow()
    rows = db.scalars(select(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )).all()
    count = 0
    for row in rows:
        if except_session_id and row.session_id == except_session_id:
            continue
        row.revoked_at = now
        count += 1
    return count


def create_access_token(user: User, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "ver": user.token_version,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired or credentials are no longer valid",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
        session_id = str(payload.get("sid") or "")
        if not session_id:
            raise ValueError("Session id missing")
    except Exception as exc:
        raise credentials_exception from exc

    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if not user or payload.get("ver") != user.token_version:
        raise credentials_exception

    session = db.scalar(select(UserSession).where(
        UserSession.session_id == session_id,
        UserSession.user_id == user.id,
    ))
    now = datetime.utcnow()
    if not session or session.revoked_at is not None or session.expires_at <= now:
        raise credentials_exception
    if session.last_seen_at + timedelta(minutes=settings.session_idle_timeout_minutes) <= now:
        session.revoked_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired due to inactivity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if session.last_seen_at + timedelta(minutes=5) <= now:
        session.last_seen_at = now
        db.commit()

    request.state.session_id = session.session_id
    request.state.user_session_id = session.id

    from .security_policy import enforce_api_policy
    enforce_api_policy(user, request)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and db.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        # Serialize app writes with preview confirmation and month close.
        db.execute(text("SELECT pg_advisory_xact_lock(2163001)"))
    db.info["actor_id"] = user.id
    db.info["reason"] = request.headers.get("X-Change-Reason", "").strip()
    db.info["correction_id"] = request.headers.get("X-Correction-ID")
    db.info["request_path"] = request.url.path
    return user


def optional_user(
    request: Request,
    token: str | None = Depends(OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)),
    db: Session = Depends(get_db),
):
    if not token:
        return None
    try:
        return get_current_user(request, token, db)
    except Exception:
        return None
