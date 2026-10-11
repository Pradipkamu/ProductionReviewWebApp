from datetime import date, datetime, timezone
from pydantic import TypeAdapter
from app.time_utils import UTCTimestamp, ist_date, ist_day_start_utc, format_ist
from app.schemas import ActionUpdate
from app.api.reviews import ReviewPointCreate
from app.api.quality import QualityActionCreate
from app.api.oee import OEEActionCreate


def test_ist_midnight_month_and_year_boundaries():
    assert ist_date(datetime(2026, 12, 31, 18, 29)) == date(2026, 12, 31)
    assert ist_date(datetime(2026, 12, 31, 18, 30)) == date(2027, 1, 1)
    assert ist_day_start_utc(date(2027, 1, 1)) == datetime(2026, 12, 31, 18, 30)
    assert format_ist(datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc)) == '01-Jan-2027 00:00 IST'


def test_offset_inputs_normalize_before_naive_database_storage():
    adapter = TypeAdapter(UTCTimestamp)
    expected = datetime(2026, 10, 10, 18, 45)
    for value in ['2026-10-11T00:15:00+05:30', '2026-10-10T18:45:00Z', '2026-10-10T18:45:00']:
        assert adapter.validate_python(value) == expected
    assert ActionUpdate(due_at='2026-10-11T00:15:00+05:30').due_at == expected
    for schema in (ReviewPointCreate, QualityActionCreate, OEEActionCreate):
        # Exercise exactly the annotated deadline field, independently of other required fields.
        field = schema.model_fields['due_at']
        assert TypeAdapter(field.annotation).validate_python('2026-10-11T00:15:00+05:30') == expected


def test_pdf_timestamp_formatter_uses_ist():
    from app.services.action_pdf import _fmt_dt
    assert _fmt_dt(datetime(2026, 10, 10, 18, 45)) == '11-Oct-2026 00:15 IST'
