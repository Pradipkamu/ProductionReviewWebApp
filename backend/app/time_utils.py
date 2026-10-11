"""UTC persistence, explicit India business-day and presentation boundaries."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Annotated
from pydantic import AfterValidator

IST = ZoneInfo("Asia/Kolkata")

def utc_naive(value: datetime) -> datetime:
    # Existing naive API values retain their historical UTC meaning.
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)

UTCTimestamp = Annotated[datetime, AfterValidator(utc_naive)]

def as_ist(value: datetime) -> datetime:
    source = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return source.astimezone(IST)

def ist_today() -> date:
    return datetime.now(IST).date()

def ist_date(value: datetime) -> date:
    return as_ist(value).date()

def ist_day_start_utc(value: date) -> datetime:
    return utc_naive(datetime.combine(value, time.min, tzinfo=IST))

def format_ist(value: datetime | None) -> str:
    return as_ist(value).strftime("%d-%b-%Y %H:%M IST") if value else ""
