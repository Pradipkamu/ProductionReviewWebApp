from fastapi.testclient import TestClient

from app.main import app
from test_governance_security import headers


def test_machine_master_fractional_manpower_pm_cost_and_history():
    client = TestClient(app)
    h = headers(client)
    payload = {
        'code': 'CNC-COST-01', 'name': 'CNC Costing Machine', 'machine_type': 'VMC',
        'plant': 'Plant 2020', 'department': 'Finish Machining', 'cost_center': 'CC-MACH',
        'manufacturer': 'Maker', 'model_number': 'X1', 'serial_number': 'SN-001',
        'commissioned_on': '2024-01-01', 'pm_done_date': '2026-09-15', 'pm_frequency_days': 90,
        'default_manpower_required': 0.5, 'rated_power_kw': 10, 'power_load_factor': 0.8,
        'air_consumption_cfm': 100, 'labor_rate_per_operator_hour': 200,
        'electricity_rate_per_kwh': 8, 'compressed_air_rate_per_1000_cuft': 5,
        'maintenance_cost_per_hour': 20, 'consumables_cost_per_hour': 10,
        'depreciation_cost_per_hour': 15, 'other_overhead_cost_per_hour': 5,
        'is_active': True, 'reason': 'Initial approved machine cost study',
    }
    response = client.post('/api/masters/machines', headers=h, json=payload)
    assert response.status_code == 200, response.text
    machine = response.json()
    assert machine['default_manpower_required'] == 0.5
    assert machine['next_pm_date'] == '2026-12-14'
    assert machine['cost']['estimated_hourly_cost'] == 244
    assert machine['cost']['cost_complete'] is True

    payload.update(rated_power_kw=12, pm_done_date='2026-10-01', reason='Rated load and PM record updated')
    updated = client.patch(f"/api/masters/machines/{machine['id']}", headers=h, json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()['cost']['estimated_hourly_cost'] == 256.8
    history = client.get(f"/api/masters/machines/{machine['id']}/history", headers=h)
    assert history.status_code == 200
    assert [row['change_type'] for row in history.json()] == ['UPDATE', 'CREATE']
    assert history.json()[0]['snapshot']['pm_done_date'] == '2026-10-01'
