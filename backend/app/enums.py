from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGEMENT = "MANAGEMENT"
    PRODUCTION = "PRODUCTION"
    QUALITY = "QUALITY"
    PLANNING = "PLANNING"
    PURCHASE = "PURCHASE"
    DISPATCH = "DISPATCH"
    VENDOR = "VENDOR"
    VIEW_ONLY = "VIEW_ONLY"


class OperationType(str, Enum):
    INTERNAL = "INTERNAL"
    VENDOR_OUT = "VENDOR_OUT"
    VENDOR_PROCESS = "VENDOR_PROCESS"
    VENDOR_IN = "VENDOR_IN"
    INSPECTION = "INSPECTION"
    PACKING = "PACKING"
    DISPATCH = "DISPATCH"
    CUSTOMER_RECEIPT = "CUSTOMER_RECEIPT"


class OEEComponent(str, Enum):
    AVAILABILITY = "AVAILABILITY"
    PERFORMANCE = "PERFORMANCE"
    QUALITY = "QUALITY"
    NON_OEE = "NON_OEE"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MonthState(str, Enum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    CLOSED = "CLOSED"


class SourceType(str, Enum):
    MANUAL = "MANUAL"
    EXCEL = "EXCEL"
    ERP = "ERP"
    AFMS = "AFMS"
    API = "API"
