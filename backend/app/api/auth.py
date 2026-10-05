from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    create_session,
    get_current_user,
    hash_password,
    record_security_event,
    request_is_https,
    revoke_user_sessions,
    verify_password,
)
from ..config import get_settings
from ..db import get_db
from ..enums import UserRole
from ..models import GovernanceAudit, PageAccessRule, SecurityEvent, User, UserSession
from ..page_access import PAGE_KEYS, REQUIRED_PAGE_KEYS, effective_page_keys, page_access_configuration
from ..schemas import LoginRequest, Token
from ..security_policy import validate_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
DUMMY_PASSWORD_HASH = hash_password("InvalidPassword-OnlyForTiming-42!", bytes(range(16)))


def serialize(user: User):
    return dict(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        session_idle_timeout_minutes=settings.session_idle_timeout_minutes,
    )


def serialize_session(row: UserSession, current_session_id: str, username: str | None = None):
    return dict(
        id=row.id,
        username=username,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        is_current=row.session_id == current_session_id,
    )


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    now = datetime.utcnow()

    if not user:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        record_security_event(db, request, "LOGIN_FAILED", success=False, username=username, detail="Unknown username")
        db.commit()
        raise HTTPException(401, "Invalid username or password")

    if user.locked_until and user.locked_until > now:
        record_security_event(db, request, "LOGIN_BLOCKED", success=False, user=user, detail="Account temporarily locked")
        db.commit()
        raise HTTPException(429, "Account temporarily locked after repeated failed sign-ins. Try again later.")

    if not user.is_active or not verify_password(payload.password, user.password_hash):
        if user.is_active:
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
        locked_now = bool(user.is_active and user.locked_until and user.locked_until > now)
        record_security_event(
            db,
            request,
            "ACCOUNT_LOCKED" if locked_now else "LOGIN_FAILED",
            success=False,
            user=user,
            detail="Inactive account" if not user.is_active else ("Too many failed passwords" if locked_now else "Invalid password"),
        )
        db.commit()
        if locked_now:
            raise HTTPException(429, "Account temporarily locked after repeated failed sign-ins. Try again later.")
        raise HTTPException(401, "Invalid username or password")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    session = create_session(db, user, request)
    record_security_event(db, request, "LOGIN_SUCCESS", success=True, user=user)
    db.commit()
    return Token(access_token=create_access_token(user, session.session_id), user=serialize(user))


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {**serialize(user), "page_access": effective_page_keys(db, user.role)}


class PageAccessUpdate(BaseModel):
    access: dict[str, list[str]]
    reason: str = Field(min_length=5, max_length=1000)


@router.get("/page-access")
def get_page_access(db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(403, "Only ADMIN can configure page visibility")
    return page_access_configuration(db)


@router.put("/page-access")
def update_page_access(
    payload: PageAccessUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(403, "Only ADMIN can configure page visibility")
    expected_roles = {role.value for role in UserRole if role != UserRole.ADMIN}
    supplied_roles = set(payload.access)
    if supplied_roles != expected_roles:
        missing = sorted(expected_roles - supplied_roles)
        extra = sorted(supplied_roles - expected_roles)
        raise HTTPException(422, f"Page access must include every non-admin role; missing={missing}, extra={extra}")
    valid_pages = set(PAGE_KEYS)
    for role, keys in payload.access.items():
        unknown = sorted(set(keys) - valid_pages)
        if unknown:
            raise HTTPException(422, f"Unknown page keys for {role}: {unknown}")
        if not REQUIRED_PAGE_KEYS.issubset(keys):
            raise HTTPException(422, f"Required account/security page cannot be hidden for {role}")

    existing = {
        (row.role, row.page_key): row
        for row in db.scalars(select(PageAccessRule)).all()
    }
    for role in sorted(expected_roles):
        visible = set(payload.access[role])
        for page_key in PAGE_KEYS:
            row = existing.get((role, page_key))
            if row is None:
                row = PageAccessRule(role=role, page_key=page_key)
                db.add(row)
            row.is_visible = page_key in visible or page_key in REQUIRED_PAGE_KEYS
            row.updated_by_id = admin.id

    counts = ", ".join(f"{role}={len(set(keys))}" for role, keys in sorted(payload.access.items()))
    record_security_event(db, request, "PAGE_ACCESS_UPDATED", success=True, user=admin, detail=counts)
    db.add(GovernanceAudit(
        actor_id=admin.id,
        event="PAGE_ACCESS_UPDATED",
        entity="page_access_rules",
        entity_id="role-matrix",
        reason=payload.reason,
    ))
    db.commit()
    return page_access_configuration(db)


@router.get("/security-status")
def security_status(request: Request, user: User = Depends(get_current_user)):
    return {
        "transport": "HTTPS" if request_is_https(request) else "HTTP",
        "https_required": settings.require_https,
        "trust_proxy_headers": settings.trust_proxy_headers,
        "session_idle_timeout_minutes": settings.session_idle_timeout_minutes,
        "access_token_expire_minutes": settings.access_token_expire_minutes,
        "login_max_failures": settings.login_max_failures,
        "login_lock_minutes": settings.login_lock_minutes,
        "role": user.role.value,
    }


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = getattr(request.state, "session_id", None)
    row = db.scalar(select(UserSession).where(UserSession.session_id == sid, UserSession.user_id == user.id))
    if row and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
    record_security_event(db, request, "LOGOUT", success=True, user=user)
    db.commit()
    return {"status": "ok"}


@router.get("/sessions")
def sessions(
    request: Request,
    all_users: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(UserSession).order_by(UserSession.last_seen_at.desc())
    if not (all_users and user.role == UserRole.ADMIN):
        q = q.where(UserSession.user_id == user.id)
    rows = db.scalars(q.limit(250)).all()
    user_map = {u.id: u.username for u in db.scalars(select(User)).all()} if all_users and user.role == UserRole.ADMIN else {user.id: user.username}
    current_sid = getattr(request.state, "session_id", "")
    return [serialize_session(r, current_sid, user_map.get(r.user_id)) for r in rows]


@router.delete("/sessions/{session_row_id}")
def revoke_session(
    session_row_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(UserSession, session_row_id)
    if not row:
        raise HTTPException(404, "Session not found")
    if row.user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(403, "You can revoke only your own sessions")
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
    record_security_event(
        db,
        request,
        "SESSION_REVOKED",
        success=True,
        user=user,
        detail=f"Session {row.id} revoked" + (" by administrator" if row.user_id != user.id else ""),
    )
    db.commit()
    return {"status": "revoked", "current_session": row.session_id == getattr(request.state, "session_id", "")}


@router.get("/security-events")
def security_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in {UserRole.ADMIN, UserRole.MANAGEMENT}:
        raise HTTPException(403, "Security audit requires Admin or Management")
    limit = max(1, min(limit, 500))
    rows = db.scalars(select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(limit)).all()
    return [{
        "id": r.id,
        "occurred_at": r.occurred_at,
        "event_type": r.event_type,
        "success": r.success,
        "username": r.username,
        "ip_address": r.ip_address,
        "user_agent": r.user_agent,
        "detail": r.detail,
    } for r in rows]


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    validate_password(payload.new_password)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(422, "New password must differ from current password")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_version += 1
    current_sid = getattr(request.state, "session_id", "")
    revoke_user_sessions(db, user.id, except_session_id=current_sid)
    record_security_event(db, request, "PASSWORD_CHANGED", success=True, user=user)
    db.add(GovernanceAudit(actor_id=user.id, event="PASSWORD_CHANGED", entity="users", entity_id=str(user.id), reason="User changed password"))
    db.commit()
    return dict(access_token=create_access_token(user, current_sid), user=serialize(user))


class PasswordReset(BaseModel):
    temporary_password: str
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    validate_password(payload.temporary_password)
    user.password_hash = hash_password(payload.temporary_password)
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.token_version += 1
    revoke_user_sessions(db, user.id)
    record_security_event(db, request, "PASSWORD_RESET", success=True, user=user, detail=f"Reset by {admin.username}")
    db.add(GovernanceAudit(actor_id=admin.id, event="PASSWORD_RESET", entity="users", entity_id=str(user_id), reason=payload.reason))
    db.commit()
    return serialize(user)


class UnlockRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: int,
    payload: UnlockRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.failed_login_attempts = 0
    user.locked_until = None
    record_security_event(db, request, "ACCOUNT_UNLOCKED", success=True, user=user, detail=f"Unlocked by {admin.username}")
    db.add(GovernanceAudit(actor_id=admin.id, event="ACCOUNT_UNLOCKED", entity="users", entity_id=str(user_id), reason=payload.reason))
    db.commit()
    return serialize(user)


class UserUpdate(BaseModel):
    role: UserRole
    is_active: bool
    reason: str = Field(min_length=5, max_length=1000)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and (payload.role != UserRole.ADMIN or not payload.is_active):
        raise HTTPException(409, "You cannot demote or disable your own admin account")
    if user.role == UserRole.ADMIN and (payload.role != UserRole.ADMIN or not payload.is_active):
        others = db.scalars(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id).with_for_update()).all()
        if not others:
            raise HTTPException(409, "At least one active administrator is required")
    before = serialize(user)
    user.role = payload.role
    user.is_active = payload.is_active
    user.token_version += 1
    revoke_user_sessions(db, user.id)
    import json
    record_security_event(db, request, "USER_UPDATED", success=True, user=user, detail=f"Changed by {admin.username}")
    db.add(GovernanceAudit(
        actor_id=admin.id,
        event="USER_UPDATED",
        entity="users",
        entity_id=str(user_id),
        reason=payload.reason,
        before_json=json.dumps(before, default=str),
        after_json=json.dumps(serialize(user), default=str),
    ))
    db.commit()
    return serialize(user)
