from decimal import Decimal


def calculate_oee(
    shift_duration_min: Decimal | float,
    planned_break_min: Decimal | float,
    downtime_min: Decimal | float,
    total_count: Decimal | float,
    good_count: Decimal | float,
    ideal_cycle_time_sec: Decimal | float,
) -> dict:
    shift = float(shift_duration_min or 0)
    breaks = float(planned_break_min or 0)
    downtime = float(downtime_min or 0)
    total = float(total_count or 0)
    good = float(good_count or 0)
    ideal_ct = float(ideal_cycle_time_sec or 0)

    planned = max(0.0, shift - breaks)
    run = max(0.0, planned - downtime)
    availability = run / planned if planned > 0 else 0.0
    theoretical_run_min = (ideal_ct * total) / 60.0 if ideal_ct > 0 else 0.0
    performance_raw = theoretical_run_min / run if run > 0 else 0.0
    performance_capped = min(1.0, max(0.0, performance_raw))
    quality = good / total if total > 0 else 0.0
    raw_oee = availability * performance_raw * quality
    reported_oee = availability * performance_capped * quality
    return {
        "planned_production_min": planned,
        "run_time_min": run,
        "availability": availability,
        "performance_raw": performance_raw,
        "performance_capped": performance_capped,
        "quality": quality,
        "oee_raw": raw_oee,
        "oee_reported": reported_oee,
        "performance_master_warning": performance_raw > 1.10,
    }
