"""Transaction-level month protection and append-only business change evidence."""
import json
from datetime import date, datetime
from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import GovernanceAudit, HistoricalCorrectionGrant, MonthStatus, User
from .enums import MonthState

PERIOD_FIELDS = {
 'process_flow_versions': ['effective_from'], 'stage_schedule_allocations': ['month','effective_from'],
 'daily_mis': ['mis_date'], 'daily_requirements': ['req_date'], 'process_daily_summary': ['summary_date'],
 'vendor_movements': ['outward_date', 'receipt_date'], 'machine_shift_production': ['production_date'],
 'machine_loss_events': ['loss_date'], 'quality_rejection_daily': ['rejection_date'],
 'quality_rejection_monthly_history': ['month'], 'schedule_revisions': ['month', 'effective_from'],
 'working_calendar': ['work_date'], 'vendor_receipts': ['receipt_date'],
 'sales_price_history': ['effective_from'], 'route_versions': ['effective_from'], 'standard_cycle_times': ['effective_from'],
 'operation_machine_map': ['effective_from'], 'operator_requirement_history': ['effective_from'],
 'machine_capacity_settings': ['effective_from'], 'machine_monthly_allocations': ['month','effective_from'],
 'casting_defect_daily': ['defect_date'], 'customer_rejection_daily': ['rejection_date'],
 'product_value_addition_history': ['effective_from'],
}
RANGE_TABLES = {'process_flow_versions', 'sales_price_history', 'route_versions', 'standard_cycle_times',
                'operation_machine_map', 'operator_requirement_history', 'machine_capacity_settings',
                'product_value_addition_history'}

def lock_month(db, month):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 2161000 + month.year * 12 + month.month})


def snapshot(obj, old=False):
    state = inspect(obj)
    out = {}
    for col in state.mapper.columns:
        if col.key in {'password_hash', 'token_version'}:
            continue
        hist = state.attrs[col.key].history
        val = hist.deleted[0] if old and hist.deleted else getattr(obj, col.key)
        out[col.key] = val
    return json.dumps(out, default=str, sort_keys=True)

@event.listens_for(Session, 'before_flush')
def protect_months(db, flush_context, instances):
    if not db.info.get('actor_id'):
        return  # seed/test fixtures and explicit migrations have no API actor
    candidates = list(db.new) + list(db.dirty) + list(db.deleted)
    for obj in candidates:
        table = getattr(obj, '__tablename__', '')
        if table in {'process_flow_versions','process_flow_stages','stage_schedule_allocations','machine_monthly_allocations'} and (obj in db.deleted or (obj in db.dirty and db.is_modified(obj,include_collections=False))):
            raise HTTPException(409,'Process definitions and allocation history are immutable; append a new revision')
        if table not in PERIOD_FIELDS or (obj in db.dirty and not db.is_modified(obj, include_collections=False)):
            continue
        periods = set()
        for field in PERIOD_FIELDS[table]:
            if table == 'vendor_movements' and obj in db.dirty:
                if field == 'outward_date' and not any(inspect(obj).attrs[k].history.has_changes() for k in ['outward_date','outward_qty','product_id','vendor_id','route_operation_id','challan_no','expected_return_date']):
                    continue
                if field == 'receipt_date':
                    # Append-only ledger guards the actual receipt date; cumulative totals do not rewrite an earlier receipt.
                    continue
            attr = inspect(obj).attrs[field]
            values = [getattr(obj, field)] + list(attr.history.deleted)
            periods.update(v.replace(day=1) for v in values if isinstance(v, date))
        if table in RANGE_TABLES:
            starts = [getattr(obj, 'effective_from')] + list(inspect(obj).attrs.effective_from.history.deleted)
            first = min(x for x in starts if x)
            # A backdated revision can alter a previously closed month downstream.
            periods.update(db.scalars(select(MonthStatus.month).where(MonthStatus.month >= first.replace(day=1), MonthStatus.status == MonthState.CLOSED)))
        for month in sorted(periods):
            lock_month(db, month)
            status = db.scalar(select(MonthStatus).where(MonthStatus.month == month).with_for_update())
            if status and status.status == MonthState.CLOSED:
                grant_id = db.info.get('correction_id')
                grant = db.get(HistoricalCorrectionGrant, int(grant_id)) if grant_id and str(grant_id).isdigit() else None
                if grant:
                    grant = db.scalar(select(HistoricalCorrectionGrant).where(HistoricalCorrectionGrant.id == grant.id).with_for_update())
                if not grant or grant.month != month or grant.user_id != db.info['actor_id'] or grant.expires_at < datetime.utcnow() or (grant.used_at and not db.info.get('grant_in_use') == grant.id):
                    raise HTTPException(409, f'Month {month:%Y-%m} is closed; reopen it or obtain a correction authorization')
                db.info['grant_in_use'] = grant.id
                db.info['reason'] = grant.reason
        before = snapshot(obj, True) if obj not in db.new else None
        after = snapshot(obj) if obj not in db.deleted else None
        if obj in db.dirty and periods and min(periods) < date.today().replace(day=1) and not db.info.get('reason'):
            reason = getattr(obj, 'reason', None)
            if not reason or not str(reason).strip():
                raise HTTPException(422, 'Historical corrections require X-Change-Reason')
        reason = db.info.get('reason') or getattr(obj, 'reason', None) or ('New business record' if obj in db.new else 'Current-period edit')
        audit = GovernanceAudit(actor_id=db.info['actor_id'], event='CREATE' if obj in db.new else 'DELETE' if obj in db.deleted else 'UPDATE',
            entity=table, entity_id=str(getattr(obj, 'id', '') or ''), month=min(periods) if periods else None,
            reason=str(reason), before_json=before, after_json=after)
        db.add(audit)
        if obj in db.new:
            db.info.setdefault('pending_audit_ids', []).append((audit,obj))

@event.listens_for(Session, 'before_commit')
def consume_grant(db):
    db.flush()
    grant_id = db.info.get('grant_in_use')
    if grant_id:
        grant = db.get(HistoricalCorrectionGrant, grant_id)
        grant.used_at = datetime.utcnow()


@event.listens_for(Session, 'after_flush_postexec')
def finish_created_evidence(db, flush_context):
    for audit,obj in db.info.pop('pending_audit_ids', []):
        audit.entity_id = str(getattr(obj,'id',''))
        audit.after_json = snapshot(obj)

@event.listens_for(Session, 'after_rollback')
def clear_rolled_back_evidence(db):
    db.info.pop('pending_audit_ids',None)
    db.info.pop('grant_in_use',None)
