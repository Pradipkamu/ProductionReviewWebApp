from ..time_utils import ist_today, ist_date, as_ist, IST
from datetime import date, datetime, time
from sqlalchemy import select, text
from ..models import Action, ActionWhyWhy, ActionReminder, AlertPolicy, AlertDeliveryLog
from ..enums import ActionStatus

def refresh_reminders(db):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(2162001)'))
    today = ist_today()
    now_local = as_ist(datetime.utcnow())
    actions = db.scalars(select(Action)).all()
    plans = {p.action_id:p for p in db.scalars(select(ActionWhyWhy))}
    existing = {(r.action_id,r.kind) for r in db.scalars(select(ActionReminder).where(ActionReminder.reminder_date==today))}
    policies = {p.code:p for p in db.scalars(select(AlertPolicy)).all()}
    policy_by_kind = {'OVERDUE': 'action_overdue', 'EFFECTIVENESS': 'action_effectiveness'}

    for action in actions:
        alerts=[]
        if action.status != ActionStatus.CLOSED and action.due_at and ist_date(action.due_at)<today:
            age=(today-ist_date(action.due_at)).days
            alerts.append(('OVERDUE','ADMIN' if age>=14 else 'MANAGEMENT' if age>=7 else 'OWNER',f'{action.action_no} overdue by {age} days'))
        plan=plans.get(action.id)
        if plan and plan.effectiveness_check_date and plan.effectiveness_check_date<today and not plan.effectiveness_result:
            alerts.append(('EFFECTIVENESS','QUALITY',f'{action.action_no} effectiveness check overdue since {plan.effectiveness_check_date}'))

        for kind,level,message in alerts:
            if (action.id,kind) in existing:
                continue
            policy = policies.get(policy_by_kind.get(kind))
            if not policy:
                db.add(ActionReminder(action_id=action.id,reminder_date=today,kind=kind,level=level,message=message))
                continue

            event_key=f'action:{action.id}:{kind}:{today.isoformat()}'
            already_logged = db.scalar(
                select(AlertDeliveryLog.id).where(
                    AlertDeliveryLog.policy_id == policy.id,
                    AlertDeliveryLog.event_key == event_key,
                    AlertDeliveryLog.channel == 'IN_APP',
                )
            )
            if already_logged:
                continue

            if not policy.enabled:
                db.add(AlertDeliveryLog(policy_id=policy.id,event_key=event_key,status='DISABLED',
                                        recipient_role=policy.recipient_roles,message=message))
                continue

            if _in_quiet_window(policy, now_local):
                db.add(AlertDeliveryLog(policy_id=policy.id,event_key=event_key,status='SUPPRESSED_QUIET_HOURS',
                                        recipient_role=policy.recipient_roles,message=message))
                continue

            db.add(ActionReminder(action_id=action.id,reminder_date=today,kind=kind,level=level,message=message))
            db.add(AlertDeliveryLog(policy_id=policy.id,event_key=event_key,status='DELIVERED',
                                    recipient_role=policy.recipient_roles,message=message,
                                    delivered_at=now_local.replace(tzinfo=None)))
    db.commit()
