from datetime import datetime, time

from sqlalchemy import select, text

from ..enums import ActionStatus, UserRole
from ..models import Action, ActionWhyWhy, ActionReminder, AlertPolicy, AlertDeliveryLog, User
from ..time_utils import ist_today, ist_date, as_ist
from .action_notifications import send_action_chat_notification


def _in_quiet_window(policy: AlertPolicy, now_local: datetime) -> bool:
    if not policy.quiet_start or not policy.quiet_end:
        return False
    try:
        start = time.fromisoformat(policy.quiet_start)
        end = time.fromisoformat(policy.quiet_end)
    except ValueError:
        return False
    current = now_local.timetz().replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _recipients(db, action: Action, level: str) -> list[int]:
    ids: set[int] = set()
    if action.owner_id:
        ids.add(action.owner_id)
    if level in {"MANAGEMENT", "ADMIN"}:
        roles = [UserRole.ADMIN] if level == "ADMIN" else [UserRole.ADMIN, UserRole.MANAGEMENT]
        ids.update(db.scalars(select(User.id).where(
            User.is_active.is_(True), User.role.in_(roles)
        )).all())
    elif level == "QUALITY":
        ids.update(db.scalars(select(User.id).where(
            User.is_active.is_(True),
            User.role.in_([UserRole.QUALITY, UserRole.MANAGEMENT, UserRole.ADMIN]),
        )).all())
    return sorted(ids)


def refresh_reminders(db):
    """Create scheduled action reminders and deliver them as system Chat messages.

    The transaction-level advisory lock serializes workers, while ActionReminder
    and AlertDeliveryLog provide a second layer of duplicate prevention.
    """
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(2162001)"))

    today = ist_today()
    now_local = as_ist(datetime.utcnow())
    actions = db.scalars(select(Action)).all()
    plans = {p.action_id: p for p in db.scalars(select(ActionWhyWhy)).all()}
    existing_today = {
        (r.action_id, r.kind)
        for r in db.scalars(select(ActionReminder).where(ActionReminder.reminder_date == today)).all()
    }
    policies = {p.code: p for p in db.scalars(select(AlertPolicy)).all()}

    for action in actions:
        if action.status == ActionStatus.CLOSED:
            continue

        events: list[tuple[str, str, str, str]] = []
        if action.due_at:
            days_to_due = (ist_date(action.due_at) - today).days
            if days_to_due == 3:
                events.append(("DUE_3_DAYS", "OWNER", "action_due_3_days",
                               f"Action closure reminder: due in 3 days ({ist_date(action.due_at)})."))
            elif days_to_due == 1:
                events.append(("DUE_1_DAY", "OWNER", "action_due_1_day",
                               f"Action closure reminder: due tomorrow ({ist_date(action.due_at)})."))
            elif days_to_due == 0:
                events.append(("DUE_TODAY", "OWNER", "action_due_today",
                               f"Action closure reminder: due today ({ist_date(action.due_at)})."))
            elif days_to_due < 0:
                days_overdue = abs(days_to_due)
                milestone = {1: ("OVERDUE_1_DAY", "OWNER"),
                             3: ("OVERDUE_3_DAYS", "MANAGEMENT"),
                             7: ("OVERDUE_7_DAYS", "MANAGEMENT"),
                             14: ("OVERDUE_14_DAYS", "ADMIN")}.get(days_overdue)
                if milestone:
                    kind, level = milestone
                    events.append((kind, level, "action_overdue",
                                   f"Action is overdue by {days_overdue} day(s). Due date was {ist_date(action.due_at)}."))

        plan = plans.get(action.id)
        if plan and plan.effectiveness_check_date and not plan.effectiveness_result:
            days_late = (today - plan.effectiveness_check_date).days
            milestone = {0: "EFFECTIVENESS_DUE", 1: "EFFECTIVENESS_1_DAY",
                         3: "EFFECTIVENESS_3_DAYS", 7: "EFFECTIVENESS_7_DAYS"}.get(days_late)
            if milestone:
                events.append((milestone, "QUALITY", "action_effectiveness",
                               f"Effectiveness verification is due/overdue since {plan.effectiveness_check_date}."))

        for kind, level, policy_code, detail in events:
            if (action.id, kind) in existing_today:
                continue
            policy = policies.get(policy_code)
            if policy and not policy.enabled:
                continue
            if policy and _in_quiet_window(policy, now_local):
                continue

            recipients = _recipients(db, action, level)
            event_date = today.isoformat()
            delivered_any = False
            for recipient_id in recipients:
                event_key = f"action:{action.id}:{kind}:{event_date}:user:{recipient_id}"
                delivered = send_action_chat_notification(
                    db,
                    action,
                    recipient_id,
                    kind=kind,
                    event_key=event_key,
                    message=(
                        f"{detail}\n"
                        f"Description: {action.problem_description or action.action_description}\n"
                        f"Please review the action and update progress/closure evidence."
                    ),
                    policy_id=policy.id if policy else None,
                )
                delivered_any = delivered_any or delivered

            # Record the reminder even when no eligible chat recipient exists;
            # the unique action/date/kind key prevents repeated scheduler work.
            db.add(ActionReminder(
                action_id=action.id,
                reminder_date=today,
                kind=kind,
                level=level,
                message=detail,
            ))
            existing_today.add((action.id, kind))

    db.commit()
