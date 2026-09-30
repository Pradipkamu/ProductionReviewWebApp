from datetime import date, datetime
from sqlalchemy import select, text
from ..models import Action, ActionWhyWhy, ActionReminder
from ..enums import ActionStatus

def refresh_reminders(db):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(2162001)'))
    today = date.today()
    actions = db.scalars(select(Action)).all()
    plans = {p.action_id:p for p in db.scalars(select(ActionWhyWhy))}
    existing = {(r.action_id,r.kind) for r in db.scalars(select(ActionReminder).where(ActionReminder.reminder_date==today))}
    for action in actions:
        alerts=[]
        if action.status != ActionStatus.CLOSED and action.due_at and action.due_at.date()<today:
            age=(today-action.due_at.date()).days
            alerts.append(('OVERDUE','ADMIN' if age>=14 else 'MANAGEMENT' if age>=7 else 'OWNER',f'{action.action_no} overdue by {age} days'))
        plan=plans.get(action.id)
        if plan and plan.effectiveness_check_date and plan.effectiveness_check_date<today and not plan.effectiveness_result:
            alerts.append(('EFFECTIVENESS','QUALITY',f'{action.action_no} effectiveness check overdue since {plan.effectiveness_check_date}'))
        for kind,level,message in alerts:
            if (action.id,kind) not in existing:
                db.add(ActionReminder(action_id=action.id,reminder_date=today,kind=kind,level=level,message=message))
    db.commit()
