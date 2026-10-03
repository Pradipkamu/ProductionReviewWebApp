from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ..models import Machine


ZERO = Decimal("0")


def _decimal(value) -> Decimal:
    return Decimal(value) if value is not None else ZERO


def machine_cost(machine: Machine, operators_per_machine=None) -> dict:
    operators = _decimal(
        operators_per_machine if operators_per_machine is not None else machine.default_manpower_required
    )
    load_factor = _decimal(machine.power_load_factor)
    labor = operators * _decimal(machine.labor_rate_per_operator_hour)
    power = _decimal(machine.rated_power_kw) * load_factor * _decimal(machine.electricity_rate_per_kwh)
    air = _decimal(machine.air_consumption_cfm) * Decimal("60") / Decimal("1000") * _decimal(
        machine.compressed_air_rate_per_1000_cuft
    )
    maintenance = _decimal(machine.maintenance_cost_per_hour)
    consumables = _decimal(machine.consumables_cost_per_hour)
    depreciation = _decimal(machine.depreciation_cost_per_hour)
    overhead = _decimal(machine.other_overhead_cost_per_hour)
    components = {
        "labor": labor,
        "power": power,
        "compressed_air": air,
        "maintenance": maintenance,
        "consumables": consumables,
        "depreciation": depreciation,
        "other_overhead": overhead,
    }
    missing = []
    if operators_per_machine is None and machine.default_manpower_required is None:
        missing.append("Default manpower")
    if machine.labor_rate_per_operator_hour is None:
        missing.append("Labor rate")
    if machine.rated_power_kw is None:
        missing.append("Rated power")
    if machine.power_load_factor is None:
        missing.append("Power load factor")
    if machine.electricity_rate_per_kwh is None:
        missing.append("Electricity rate")
    if machine.air_consumption_cfm is None:
        missing.append("Air consumption")
    elif machine.air_consumption_cfm > 0 and machine.compressed_air_rate_per_1000_cuft is None:
        missing.append("Compressed-air rate")
    return {
        "operators_used": float(operators),
        "components": {key: float(value) for key, value in components.items()},
        "estimated_hourly_cost": float(sum(components.values(), ZERO)),
        "cost_complete": not missing,
        "cost_missing": missing,
    }


def next_pm_date(machine: Machine):
    if machine.pm_done_date and machine.pm_frequency_days:
        return machine.pm_done_date + timedelta(days=machine.pm_frequency_days)
    return None
