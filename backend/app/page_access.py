from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import UserRole
from .models import PageAccessRule


PAGE_CATALOG = (
    {"key": "insights", "label": "Exceptions / Data Quality", "path": "/insights"},
    {"key": "diagnostics", "label": "System Diagnostics", "path": "/diagnostics"},
    {"key": "account", "label": "Security / Users", "path": "/account", "required": True},
    {"key": "governance", "label": "Month Close / Audit", "path": "/governance"},
    {"key": "daily_review", "label": "Daily Review", "path": "/"},
    {"key": "mis", "label": "MIS", "path": "/mis"},
    {"key": "schedule", "label": "Schedule / Price / Calendar", "path": "/schedule"},
    {"key": "machine_master", "label": "Machine Master", "path": "/machine-master"},
    {"key": "capacity", "label": "Capacity / Manpower", "path": "/capacity"},
    {"key": "process", "label": "Process Monitor", "path": "/process"},
    {"key": "process_actuals", "label": "Process Actuals / Edit", "path": "/process-actuals"},
    {"key": "quality", "label": "Quality / Rejection", "path": "/quality"},
    {"key": "reports", "label": "Compliance Reports", "path": "/reports"},
    {"key": "management_reports", "label": "Management Reports", "path": "/management-reports"},
    {"key": "actions", "label": "Actions", "path": "/actions"},
    {"key": "vendor", "label": "Vendor WIP", "path": "/vendor"},
    {"key": "oee", "label": "Machine / OEE", "path": "/oee"},
    {"key": "analytics", "label": "Analytics", "path": "/analytics"},
    {"key": "masters", "label": "Masters", "path": "/masters"},
    {"key": "import", "label": "Excel Import", "path": "/import"},
)

PAGE_KEYS = tuple(page["key"] for page in PAGE_CATALOG)
REQUIRED_PAGE_KEYS = frozenset(page["key"] for page in PAGE_CATALOG if page.get("required"))

DEFAULT_ROLE_RESTRICTIONS = {
    "diagnostics": {UserRole.ADMIN, UserRole.MANAGEMENT},
    "governance": {UserRole.ADMIN, UserRole.MANAGEMENT},
    "import": {UserRole.ADMIN, UserRole.PLANNING, UserRole.QUALITY, UserRole.PRODUCTION},
}


def default_page_keys(role: UserRole) -> list[str]:
    if role == UserRole.ADMIN:
        return list(PAGE_KEYS)
    return [
        key for key in PAGE_KEYS
        if key not in DEFAULT_ROLE_RESTRICTIONS or role in DEFAULT_ROLE_RESTRICTIONS[key]
    ]


def effective_page_keys(db: Session, role: UserRole) -> list[str]:
    if role == UserRole.ADMIN:
        return list(PAGE_KEYS)
    visible = set(default_page_keys(role))
    rows = db.scalars(select(PageAccessRule).where(PageAccessRule.role == role.value)).all()
    for row in rows:
        if row.page_key not in PAGE_KEYS or row.page_key in REQUIRED_PAGE_KEYS:
            continue
        if row.is_visible:
            visible.add(row.page_key)
        else:
            visible.discard(row.page_key)
    visible.update(REQUIRED_PAGE_KEYS)
    return [key for key in PAGE_KEYS if key in visible]


def page_access_configuration(db: Session) -> dict:
    return {
        "roles": [role.value for role in UserRole],
        "pages": list(PAGE_CATALOG),
        "access": {role.value: effective_page_keys(db, role) for role in UserRole},
    }
