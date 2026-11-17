from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import UserRole
from .models import PageAccessRule


PAGE_CATALOG = (
    {"key": "control_tower", "label": "Executive Control Tower", "path": "/control-tower"},
    {"key": "dispatch_intelligence", "label": "Dispatch vs Actual", "path": "/dispatch-intelligence"},
    {"key": "capacity_intelligence", "label": "Machine Load Intelligence", "path": "/capacity-intelligence"},
    {"key": "operations_intelligence", "label": "Operations Intelligence", "path": "/operations-intelligence"},
    {"key": "management_assistant", "label": "Management Assistant / Alerts", "path": "/management-assistant"},
    {"key": "insights", "label": "Exceptions / Data Quality", "path": "/insights"},
    {"key": "diagnostics", "label": "System Diagnostics", "path": "/diagnostics"},
    {"key": "account", "label": "Security / Users", "path": "/account", "required": True},
    {"key": "governance", "label": "Month Close / Audit", "path": "/governance"},
    {"key": "daily_review", "label": "Daily Review", "path": "/"},
    {"key": "daily_meeting", "label": "Daily Review Meeting", "path": "/daily-meeting"},
    {"key": "mis", "label": "MIS", "path": "/mis"},
    {"key": "schedule", "label": "Schedule / Price / Calendar", "path": "/schedule"},
    {"key": "machine_master", "label": "Machine Master", "path": "/machine-master"},
    {"key": "product_master", "label": "Product Update", "path": "/product-master"},
    {"key": "capacity", "label": "Capacity / Manpower", "path": "/capacity"},
    {"key": "process", "label": "Process Monitor", "path": "/process"},
    {"key": "process_actuals", "label": "Process Actuals / Edit", "path": "/process-actuals"},
    {"key": "quality", "label": "Quality / Rejection", "path": "/quality"},
    {"key": "casting_quality", "label": "Casting Quality", "path": "/casting-quality"},
    {"key": "customer_quality", "label": "Customer Quality", "path": "/customer-quality"},
    {"key": "reports", "label": "Compliance Reports", "path": "/reports"},
    {"key": "management_reports", "label": "Management Reports", "path": "/management-reports"},
    {"key": "actions", "label": "Actions", "path": "/actions"},
    {"key": "admin_action_review", "label": "User-wise Action Review", "path": "/admin-action-review"},
    {"key": "vendor", "label": "Vendor WIP", "path": "/vendor"},
    {"key": "oee", "label": "Machine / OEE", "path": "/oee"},
    {"key": "analytics", "label": "Analytics", "path": "/analytics"},
    {"key": "masters", "label": "Masters", "path": "/masters"},
    {"key": "import", "label": "Excel Import", "path": "/import"},
)

PAGE_KEYS = tuple(page["key"] for page in PAGE_CATALOG)
REQUIRED_PAGE_KEYS = frozenset(page["key"] for page in PAGE_CATALOG if page.get("required"))

DEFAULT_ROLE_RESTRICTIONS = {
    "admin_action_review": {UserRole.ADMIN},
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


# Reserved permission stored in the existing page_access_rules table.
CHAT_SEND_KEY = "chat_send"

def default_chat_send_roles() -> list[str]:
    return [role.value for role in UserRole if role != UserRole.ADMIN]

def chat_send_roles(db: Session) -> list[str]:
    enabled = set(default_chat_send_roles())
    rows = db.scalars(select(PageAccessRule).where(PageAccessRule.page_key == CHAT_SEND_KEY)).all()
    if rows:
        for row in rows:
            if row.role in enabled:
                if row.is_visible: enabled.add(row.role)
                else: enabled.discard(row.role)
    return sorted(enabled)

def can_send_chat(db: Session, user: object) -> bool:
    role = getattr(user, "role", None)
    return role == UserRole.ADMIN or (not getattr(user, "chat_disabled", False) and role is not None and role.value in set(chat_send_roles(db)))
