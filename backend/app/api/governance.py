from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db
from ..enums import MonthState
from ..governance import lock_month
from ..models import MonthStatus, HistoricalCorrectionGrant, GovernanceAudit, User

router = APIRouter(prefix='/governance', tags=['governance'])
class MonthCommand(BaseModel):
    month: date
    reason: str = Field(min_length=5, max_length=1000)
class GrantCommand(MonthCommand):
    user_id: int

@router.get('/months')
def months(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(MonthStatus).order_by(MonthStatus.month.desc())).all()

@router.post('/months/{command}')
def month_command(command: str, payload: MonthCommand, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if command not in {'close', 'reopen'}:
        raise HTTPException(404, 'Unknown month command')
    month = payload.month.replace(day=1)
    lock_month(db, month)
    row = db.scalar(select(MonthStatus).where(MonthStatus.month == month).with_for_update())
    if not row:
        row = MonthStatus(month=month, status=MonthState.OPEN); db.add(row)
    old = row.status.value
    row.status = MonthState.CLOSED if command == 'close' else MonthState.OPEN
    if old == row.status.value:
        raise HTTPException(409, f'Month is already {old}')
    row.closed_by_id = user.id if command == 'close' else None
    row.closed_at = datetime.utcnow() if command == 'close' else None
    row.remark = payload.reason
    db.add(GovernanceAudit(actor_id=user.id, event='MONTH_' + command.upper(), entity='month_status', month=month, reason=payload.reason, before_json=old, after_json=row.status.value))
    db.commit()
    return {'month': month, 'status': row.status.value}

@router.post('/corrections')
def authorize(payload: GrantCommand, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    target = db.get(User, payload.user_id)
    if not target or not target.is_active or target.role.value == 'VIEW_ONLY':
        raise HTTPException(422, 'Correction recipient must be an active user with write access')
    grant = HistoricalCorrectionGrant(month=payload.month.replace(day=1), user_id=payload.user_id, approved_by_id=user.id,
        reason=payload.reason, expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(grant); db.flush()
    db.add(GovernanceAudit(actor_id=user.id, event='CORRECTION_AUTHORIZED', entity='historical_correction_grants', entity_id=str(grant.id), month=grant.month, reason=payload.reason))
    db.commit()
    return {'correction_id': grant.id, 'expires_at': grant.expires_at, 'month': grant.month}

@router.get('/audit')
def audit(month: date | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role.value not in {'ADMIN', 'MANAGEMENT'}:
        raise HTTPException(403, 'Audit access requires Admin or Management')
    q = select(GovernanceAudit)
    if month:
        q = q.where(GovernanceAudit.month == month.replace(day=1))
    return db.scalars(q.order_by(GovernanceAudit.id.desc()).limit(500)).all()
