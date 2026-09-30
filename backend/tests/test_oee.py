from app.services.oee import calculate_oee


def test_oee_calculation_and_raw_performance():
    r = calculate_oee(480, 45, 75, 610, 590, 36)
    assert round(r["availability"], 4) == round(360/435, 4)
    assert r["performance_raw"] > 1.0
    assert r["performance_capped"] == 1.0
    assert round(r["quality"], 4) == round(590/610, 4)
    assert r["performance_master_warning"] is False  # 101.7%, below 110% warning
    assert 0.79 < r["oee_reported"] < 0.81
