from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .config import get_settings
from .enums import OEEComponent, UserRole
from .models import LossCategory, User

DEFAULT_LOSSES = [
    ("BREAKDOWN", "Breakdown", OEEComponent.AVAILABILITY),
    ("TOOL_CHANGE", "Tool Change", OEEComponent.AVAILABILITY),
    ("SETUP", "Setup / Changeover", OEEComponent.AVAILABILITY),
    ("NO_MATERIAL", "No Material", OEEComponent.AVAILABILITY),
    ("NO_OPERATOR", "No Operator", OEEComponent.AVAILABILITY),
    ("POWER_FAILURE", "Power Failure", OEEComponent.AVAILABILITY),
    ("MINOR_STOP", "Minor Stop", OEEComponent.PERFORMANCE),
    ("REDUCED_SPEED", "Reduced Speed / Cycle Time Loss", OEEComponent.PERFORMANCE),
    ("REJECTION", "Rejection", OEEComponent.QUALITY),
    ("REWORK", "Rework", OEEComponent.QUALITY),
    ("STARTUP_REJECT", "Startup Rejection", OEEComponent.QUALITY),
]


def seed_defaults(db: Session) -> None:
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == settings.admin_username))
    if not user:
        db.add(User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            full_name=settings.admin_full_name,
            role=UserRole.ADMIN,
            is_active=True,
        ))
    for code, name, component in DEFAULT_LOSSES:
        if not db.scalar(select(LossCategory).where(LossCategory.code == code)):
            db.add(LossCategory(code=code, name=name, oee_component=component))
    db.commit()
