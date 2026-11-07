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


def aggregate_oee_entries(items) -> dict:
    """Aggregate product rows without counting a shared machine shift more than once.

    MachineShiftProduction is product/operation scoped, while shift duration,
    planned breaks and machine downtime describe the machine's shift. When a
    machine runs multiple products in one shift, use the maximum recorded
    machine-time values for that machine/date/shift and sum product output and
    ideal production time. Across different machines or shifts, machine time
    remains additive.
    """
    if not items:
        return calculate_oee(0, 0, 0, 0, 0, 0)

    shift_groups = {}
    total_count = 0.0
    good_count = 0.0
    ideal_total_sec = 0.0
    for row in items:
        key = (getattr(row, "machine_id", None), getattr(row, "production_date", None), getattr(row, "shift", None))
        group = shift_groups.setdefault(key, {"shift": 0.0, "breaks": 0.0, "downtime": 0.0,
                                               "shift_values": set(), "break_values": set(), "downtime_values": set()})
        shift_value = float(row.shift_duration_min or 0)
        break_value = float(row.planned_break_min or 0)
        downtime_value = float(row.downtime_min or 0)
        group["shift"] = max(group["shift"], shift_value)
        group["breaks"] = max(group["breaks"], break_value)
        group["downtime"] = max(group["downtime"], downtime_value)
        group["shift_values"].add(shift_value)
        group["break_values"].add(break_value)
        group["downtime_values"].add(downtime_value)
        quantity = float(row.total_count or 0)
        total_count += quantity
        good_count += float(row.good_count or 0)
        ideal_total_sec += float(row.ideal_cycle_time_sec or 0) * quantity

    shift_duration = sum(group["shift"] for group in shift_groups.values())
    planned_break = sum(group["breaks"] for group in shift_groups.values())
    downtime = sum(group["downtime"] for group in shift_groups.values())
    # Equivalent weighted cycle preserves the sum of ideal production time.
    weighted_cycle = ideal_total_sec / total_count if total_count > 0 else 0.0
    result = calculate_oee(shift_duration, planned_break, downtime, total_count, good_count, weighted_cycle)
    result["shared_shift_time_conflict_count"] = sum(
        1 for group in shift_groups.values()
        if len(group["shift_values"]) > 1 or len(group["break_values"]) > 1 or len(group["downtime_values"]) > 1
    )
    return result
