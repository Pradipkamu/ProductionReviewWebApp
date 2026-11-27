import pytest
from fastapi import HTTPException

from app.api.oee import (
    MAX_OEE_BULK_ENTRIES,
    MAX_OEE_BULK_LOSSES_PER_ENTRY,
    MAX_OEE_BULK_LOSS_ROWS,
    _oee_bulk_entry_count_error,
    _validate_oee_bulk_commit_entries,
    _validate_oee_bulk_loss_events,
)


@pytest.mark.parametrize("entry_count", [1, 200, 201, 999, 1000])
def test_bulk_import_accepts_entry_counts_up_to_one_thousand(entry_count):
    _validate_oee_bulk_commit_entries([{}] * entry_count)


def test_bulk_import_rejects_empty_entry_list():
    with pytest.raises(HTTPException) as exc:
        _validate_oee_bulk_commit_entries([])
    assert exc.value.status_code == 422
    assert "between 1 and 1000" in exc.value.detail


def test_bulk_import_rejects_more_than_one_thousand_entries():
    with pytest.raises(HTTPException) as exc:
        _validate_oee_bulk_commit_entries([{}] * 1001)
    assert exc.value.status_code == 422
    assert "maximum is 1000" in exc.value.detail
    assert "Split the workbook" in exc.value.detail


def test_preview_returns_clear_error_when_workbook_exceeds_entry_limit():
    message = _oee_bulk_entry_count_error(1001)
    assert message is not None
    assert "1001 validated entries" in message
    assert "maximum is 1000" in message
    assert _oee_bulk_entry_count_error(1000) is None


@pytest.mark.parametrize("loss_count", [0, 1, 30])
def test_bulk_import_accepts_up_to_thirty_loss_events_per_entry(loss_count):
    _validate_oee_bulk_loss_events([{}] * loss_count)


def test_bulk_import_rejects_more_than_thirty_loss_events_per_entry():
    with pytest.raises(HTTPException) as exc:
        _validate_oee_bulk_loss_events([{}] * 31)
    assert exc.value.status_code == 422
    assert "no more than 30 loss events" in exc.value.detail


def test_template_capacity_matches_bulk_import_limits():
    assert MAX_OEE_BULK_ENTRIES == 1000
    assert MAX_OEE_BULK_LOSSES_PER_ENTRY == 30
    assert MAX_OEE_BULK_LOSS_ROWS == 30000
