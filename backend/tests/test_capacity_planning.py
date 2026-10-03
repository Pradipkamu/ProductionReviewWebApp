from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.enums import OperationType
from app.main import app
from app.models import (
    DailyRequirement, Machine, Operation, Product, RouteOperation, RouteVersion,
    StandardCycleTime, WorkingCalendar,
)
from test_governance_security import headers


def _setup_context():
    with SessionLocal() as db:
        product = Product(code='CAP-P1', name='Capacity Part', plant='P1')
        operation = Operation(code='CAP-OP10', name='Machining OP10', operation_type=OperationType.INTERNAL)
        m1 = Machine(code='CAP-M1', name='Machine 1')
        m2 = Machine(code='CAP-M2', name='Machine 2')
        db.add_all([product, operation, m1, m2]); db.flush()
        route = RouteVersion(product_id=product.id, revision_no=1, effective_from=date(2026, 1, 1), is_active=True)
        db.add(route); db.flush()
        ro = RouteOperation(route_version_id=route.id, operation_id=operation.id, sequence_no=10)
        db.add(ro); db.flush()
        d = date(2026, 1, 1)
        while d.month == 1:
            db.add(WorkingCalendar(work_date=d, plant='P1', is_working_day=d in {date(2026,1,2), date(2026,1,3)}))
            d += timedelta(days=1)
        db.add_all([
            DailyRequirement(req_date=date(2026,1,2), product_id=product.id, route_operation_id=ro.id, revised_plan_qty=600),
            DailyRequirement(req_date=date(2026,1,3), product_id=product.id, route_operation_id=ro.id, revised_plan_qty=600),
        ])
        db.commit()
        return product.id, ro.id, m1.id, m2.id


def _post(client, h, path, body):
    response = client.post(path, headers=h, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_effective_cycle_operator_capacity_and_monthly_machine_allocation():
    product_id, route_operation_id, m1, m2 = _setup_context()
    client = TestClient(app); h = headers(client)
    for machine_id, priority in ((m1, 1), (m2, 2)):
        _post(client, h, '/api/masters/machine-maps', {
            'route_operation_id': route_operation_id, 'machine_id': machine_id,
            'effective_from': '2026-01-01', 'priority': priority, 'reason': 'Approved part machine setup',
        })
        _post(client, h, '/api/masters/cycle-times', {
            'route_operation_id': route_operation_id, 'machine_id': machine_id,
            'effective_from': '2026-01-01', 'ideal_cycle_time_sec': 55,
            'standard_cycle_time_sec': 60, 'pieces_per_cycle': 1, 'reason': 'Initial time study',
        })
        _post(client, h, '/api/capacity/operator-requirements', {
            'route_operation_id': route_operation_id, 'machine_id': machine_id,
            'effective_from': '2026-01-01', 'operators_per_machine': 0.5,
            'reason': 'One operator handles two machines',
        })
        _post(client, h, '/api/capacity/machine-settings', {
            'machine_id': machine_id, 'effective_from': '2026-01-01',
            'shifts_per_day': 1, 'shift_minutes': 480, 'planned_break_minutes': 0,
            'planning_efficiency': 1, 'reason': 'Approved January capacity pattern',
        })

    # Effective-dated CT change reduces M1 capacity only from 3-Jan onward.
    _post(client, h, '/api/masters/cycle-times', {
        'route_operation_id': route_operation_id, 'machine_id': m1,
        'effective_from': '2026-01-03', 'ideal_cycle_time_sec': 110,
        'standard_cycle_time_sec': 120, 'pieces_per_cycle': 1, 'reason': 'New tool cycle study',
    })
    _post(client, h, '/api/masters/machine-maps', {
        'route_operation_id': route_operation_id, 'machine_id': m1,
        'effective_from': '2026-01-03', 'priority': 1, 'reason': 'Mapping reviewed with new tooling',
    })
    plan = client.get(f'/api/capacity/plan?product_id={product_id}&month=2026-01-01', headers=h).json()
    operation = plan['operations'][0]
    machines = {x['machine_id']: x for x in operation['machines']}
    assert operation['schedule_qty'] == 1200
    assert machines[m1]['capacity_qty'] == 720
    assert machines[m2]['capacity_qty'] == 960
    assert len(operation['machines']) == 2  # mid-month master revisions do not duplicate a machine
    assert machines[m1]['allocation_qty'] == 720
    assert machines[m2]['allocation_qty'] == 480
    assert operation['operators_required'] == 1

    saved = _post(client, h, '/api/capacity/allocations', {
        'product_id': product_id, 'route_operation_id': route_operation_id,
        'month': '2026-01-01', 'effective_from': '2026-01-01',
        'reason': 'January schedule machine loading approved',
        'allocations': [{'machine_id': m1, 'allocated_qty': 720}, {'machine_id': m2, 'allocated_qty': 480}],
    })
    assert saved['revision_no'] == 1
    history = client.get(f'/api/capacity/allocations/history?product_id={product_id}&route_operation_id={route_operation_id}&month=2026-01-01', headers=h).json()
    assert len(history) == 2 and {x['machine'] for x in history} == {'CAP-M1', 'CAP-M2'}

    master = client.get(f'/api/capacity/master-history?route_operation_id={route_operation_id}&machine_id={m1}', headers=h).json()
    assert len(master['cycle_times']) == 2
    assert master['cycle_times'][1]['effective_to'] == '2026-01-02'
    with SessionLocal() as db:
        cycles = db.scalars(select(StandardCycleTime).where(StandardCycleTime.machine_id == m1).order_by(StandardCycleTime.effective_from)).all()
        assert cycles[0].effective_to == date(2026,1,2)
