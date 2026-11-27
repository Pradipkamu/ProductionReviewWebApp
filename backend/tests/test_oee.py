from types import SimpleNamespace

from app.services.oee import aggregate_oee_entries, calculate_oee


def test_oee_calculation_and_raw_performance():
    r = calculate_oee(480, 45, 75, 610, 590, 36)
    assert round(r["availability"], 4) == round(360/435, 4)
    assert r["performance_raw"] > 1.0
    assert r["performance_capped"] == 1.0
    assert round(r["quality"], 4) == round(590/610, 4)
    assert r["performance_master_warning"] is False  # 101.7%, below 110% warning
    assert 0.79 < r["oee_reported"] < 0.81


def test_oee_aggregation_counts_shared_machine_shift_time_once():
    # Two products share one machine shift. Their output and ideal production
    # time add, but the same 480-minute shift, 45-minute break and 60-minute
    # downtime must not be counted twice.
    rows = [
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="A",
                        shift_duration_min=480, planned_break_min=45, downtime_min=60,
                        total_count=100, good_count=98, ideal_cycle_time_sec=30),
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="A",
                        shift_duration_min=480, planned_break_min=45, downtime_min=60,
                        total_count=200, good_count=195, ideal_cycle_time_sec=60),
    ]
    result = aggregate_oee_entries(rows)
    assert result["planned_production_min"] == 435
    assert result["run_time_min"] == 375
    assert round(result["availability"], 8) == round(375 / 435, 8)
    assert round(result["quality"], 8) == round(293 / 300, 8)
    assert round(result["performance_raw"], 8) == round((30 * 100 + 60 * 200) / 60 / 375, 8)
    assert result["shared_shift_time_conflict_count"] == 0


def test_oee_aggregation_adds_distinct_machine_shifts():
    rows = [
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="A",
                        shift_duration_min=480, planned_break_min=45, downtime_min=30,
                        total_count=100, good_count=95, ideal_cycle_time_sec=30),
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="B",
                        shift_duration_min=480, planned_break_min=45, downtime_min=20,
                        total_count=100, good_count=96, ideal_cycle_time_sec=30),
    ]
    result = aggregate_oee_entries(rows)
    assert result["planned_production_min"] == 870
    assert result["run_time_min"] == 820
    assert round(result["quality"], 8) == round(191 / 200, 8)


def test_oee_aggregation_flags_conflicting_shared_shift_time():
    rows = [
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="A",
                        shift_duration_min=480, planned_break_min=45, downtime_min=30,
                        total_count=100, good_count=95, ideal_cycle_time_sec=30),
        SimpleNamespace(machine_id=1, production_date="2026-11-07", shift="A",
                        shift_duration_min=480, planned_break_min=45, downtime_min=45,
                        total_count=100, good_count=96, ideal_cycle_time_sec=30),
    ]
    result = aggregate_oee_entries(rows)
    assert result["planned_production_min"] == 435
    assert result["run_time_min"] == 390
    assert result["shared_shift_time_conflict_count"] == 1

def test_machine_entry_derives_total_count_from_good_and_reject():
    from datetime import date
    from app.schemas import MachineEntryCreate

    entry = MachineEntryCreate(
        production_date=date(2026, 11, 7), shift="A", product_id=1,
        route_operation_id=1, machine_id=1, operator_id=1, good_count=970, reject_count=30,
    )
    assert entry.total_count == 1000


def test_machine_entry_keeps_legacy_unclassified_total_count():
    from datetime import date
    from app.schemas import MachineEntryCreate

    entry = MachineEntryCreate(
        production_date=date(2026, 11, 7), shift="A", product_id=1,
        route_operation_id=1, machine_id=1, operator_id=1, total_count=1005,
        good_count=970, reject_count=30,
    )
    assert entry.total_count == 1005


def test_availability_loss_quantity_uses_effective_cycle_and_whole_pieces():
    from decimal import Decimal
    from types import SimpleNamespace
    from app.api.oee import _calculated_loss_qty
    from app.enums import OEEComponent

    availability = SimpleNamespace(oee_component=OEEComponent.AVAILABILITY)
    performance = SimpleNamespace(oee_component=OEEComponent.PERFORMANCE)
    assert _calculated_loss_qty(Decimal("30"), availability, Decimal("12")) == Decimal("150")
    assert _calculated_loss_qty(Decimal("30"), performance, Decimal("12")) == Decimal("0")


def test_availability_loss_events_sum_to_rounded_total_quantity():
    from decimal import Decimal
    from types import SimpleNamespace
    from app.api.oee import _allocate_availability_loss_qty
    from app.enums import OEEComponent

    category = SimpleNamespace(oee_component=OEEComponent.AVAILABILITY)
    events = [
        ({"duration_min": Decimal("1"), "qty_loss": Decimal("0")}, category),
        ({"duration_min": Decimal("1"), "qty_loss": Decimal("0")}, category),
        ({"duration_min": Decimal("1"), "qty_loss": Decimal("0")}, category),
    ]
    _allocate_availability_loss_qty(events, Decimal("100"))
    assert sum(item["qty_loss"] for item, _ in events) == Decimal("2")
