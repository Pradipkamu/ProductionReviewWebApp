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
    assert result["availability"] == 375 / 435
    assert result["quality"] == 293 / 300
    assert result["performance_raw"] == (30 * 100 + 60 * 200) / 60 / 375


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
    assert result["quality"] == 191 / 200
