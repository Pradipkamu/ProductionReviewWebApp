from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import create_access_token, get_current_user, verify_password, hash_password
from ..security_policy import validate_password
from ..db import get_db
from ..enums import UserRole
from ..models import User, GovernanceAudit
from ..schemas import LoginRequest, Token

router = APIRouter(prefix='/auth', tags=['auth'])

def serialize(user):
    return dict(id=user.id, username=user.username, full_name=user.full_name, role=user.role.value,
                is_active=user.is_active, must_change_password=user.must_change_password)

@router.post('/login', response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username, User.is_active.is_(True)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Invalid username or password')
    return Token(access_token=create_access_token(user), user=serialize(user))

@router.get('/me')
def me(user: User = Depends(get_current_user)):
    return serialize(user)

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

@router.post('/change-password')
def change_password(payload: PasswordChange, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, 'Current password is incorrect')
    validate_password(payload.new_password)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(422, 'New password must differ from current password')
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_version += 1
    db.add(GovernanceAudit(actor_id=user.id, event='PASSWORD_CHANGED', entity='users', entity_id=str(user.id), reason='User changed password'))
    db.commit()
    return dict(access_token=create_access_token(user), user=serialize(user))

class PasswordReset(BaseModel):
    temporary_password: str
    reason: str = Field(min_length=5, max_length=1000)

@router.post('/users/{user_id}/reset-password')
def reset_password(user_id: int, payload: PasswordReset, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, 'User not found')
    validate_password(payload.temporary_password)
    user.password_hash = hash_password(payload.temporary_password)
    user.must_change_password = True
    user.token_version += 1
    db.add(GovernanceAudit(actor_id=admin.id, event='PASSWORD_RESET', entity='users', entity_id=str(user_id), reason=payload.reason))
    db.commit()
    return serialize(user)

class UserUpdate(BaseModel):
    role: UserRole
    is_active: bool
    reason: str = Field(min_length=5, max_length=1000)

@router.patch('/users/{user_id}')
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, 'User not found')
    if user.id == admin.id and (payload.role != UserRole.ADMIN or not payload.is_active):
        raise HTTPException(409, 'You cannot demote or disable your own admin account')
    if user.role == UserRole.ADMIN and (payload.role != UserRole.ADMIN or not payload.is_active):
        others = db.scalars(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id).with_for_update()).all()
        if not others:
            raise HTTPException(409, 'At least one active administrator is required')
    before = serialize(user)
    user.role = payload.role; user.is_active = payload.is_active; user.token_version += 1
    import json
    db.add(GovernanceAudit(actor_id=admin.id, event='USER_UPDATED', entity='users', entity_id=str(user_id), reason=payload.reason,
                           before_json=json.dumps(before), after_json=json.dumps(serialize(user))))
    db.commit()
    return serialize(user)
