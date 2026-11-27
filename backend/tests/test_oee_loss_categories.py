from app.enums import OEEComponent
from app.seed import DEFAULT_LOSSES


def test_additional_availability_loss_categories_are_seeded():
    seeded = {code: (name, component) for code, name, component in DEFAULT_LOSSES}

    expected = {
        "PREVENTIVE_MAINTENANCE": "Preventive Maintenance",
        "WAITING_QUALITY_APPROVAL": "Waiting for Quality Approval",
        "FIXTURE_CHANGE": "Fixture Change",
        "MACHINE_ADJUSTMENT": "Machine Adjustment",
        "LINE_ORGANIZATION": "Line Organization Loss",
    }

    for code, name in expected.items():
        assert seeded[code] == (name, OEEComponent.AVAILABILITY)


def test_existing_performance_and_quality_loss_seeds_are_preserved():
    seeded = {code: component for code, _name, component in DEFAULT_LOSSES}

    assert seeded["MINOR_STOP"] == OEEComponent.PERFORMANCE
    assert seeded["REDUCED_SPEED"] == OEEComponent.PERFORMANCE
    assert seeded["REJECTION"] == OEEComponent.QUALITY
    assert seeded["REWORK"] == OEEComponent.QUALITY
    assert seeded["STARTUP_REJECT"] == OEEComponent.QUALITY
