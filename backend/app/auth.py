import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "ver": user.token_version,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except Exception as exc:
        raise credentials_exception from exc
    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if not user or payload.get("ver") != user.token_version:
        raise credentials_exception
    from .security_policy import enforce_api_policy
    enforce_api_policy(user, request)
    if request.method not in {'GET','HEAD','OPTIONS'} and db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        # Serialize app writes with preview confirmation and month close.
        db.execute(text('SELECT pg_advisory_xact_lock(2163001)'))
    db.info['actor_id'] = user.id
    db.info['reason'] = request.headers.get('X-Change-Reason', '').strip()
    db.info['correction_id'] = request.headers.get('X-Correction-ID')
    db.info['request_path'] = request.url.path
    return user


def optional_user(request: Request, token: str | None = Depends(OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)), db: Session = Depends(get_db)):
    if not token:
        return None
    try:
        return get_current_user(request, token, db)
    except Exception:
        return None
