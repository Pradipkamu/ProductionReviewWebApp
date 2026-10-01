from datetime import date
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.db import SessionLocal
from app.models import Product, Machine, Operation, RouteVersion, RouteOperation, OperationMachineMap, StandardCycleTime, MachineShiftProduction, ShopCapture, User
from app.enums import UserRole
from app.auth import hash_password
from app.services.shop_capture import parse_report, read_image, ocr_image
from test_governance_security import headers


def picture(text='CNC 1 - K405 - 235:190'):
    image=Image.new('RGB',(1200,250),'white')
    try:font=ImageFont.truetype('DejaVuSans.ttf',36)
    except OSError:font=ImageFont.load_default(size=36)
    ImageDraw.Draw(image).text((30,40),text,font=font,fill='black')
    out=BytesIO();image.save(out,format='PNG');return out.getvalue()


def new_capture(c,h,monkeypatch,text='CNC 1 = 190'):
    monkeypatch.setattr('app.api.shop_capture.ocr_image',lambda _:text)
    r=c.post('/api/shop-capture/upload',headers=h,files={'file':('shift.png',picture(text),'image/png')})
    assert r.status_code==200,r.text
    return r.json()


def prepared(c,h,monkeypatch):
    with SessionLocal() as db:
        p=Product(code='K405',name='Part',plant='Plant 1');m=Machine(code='CNC1',name='CNC 1');o=Operation(code='OP10',name='Turning')
        db.add_all([p,m,o]);db.flush()
        rv=RouteVersion(product_id=p.id,revision_no=1,effective_from=date(2026,1,1));db.add(rv);db.flush()
        ro=RouteOperation(route_version_id=rv.id,operation_id=o.id,sequence_no=1);db.add(ro);db.flush()
        db.add_all([OperationMachineMap(machine_id=m.id,route_operation_id=ro.id,effective_from=date(2026,1,1)),StandardCycleTime(route_operation_id=ro.id,machine_id=m.id,effective_from=date(2026,1,1),ideal_cycle_time_sec=60)])
        ids=dict(machine_id=m.id,product_id=p.id,route_operation_id=ro.id);db.commit()
    x=new_capture(c,h,monkeypatch);d=x['draft'];d.update(plant='Plant 1',shop='Machine Shop',production_date='2026-10-01',shift='A')
    d['rows'][0].update(**ids,disposition='machine',good_count=185,shift_duration_min=480,planned_break_min=30,downtime_min=20,ideal_cycle_time_sec=60,reason='Fresh count verified against source')
    r=c.put(f"/api/shop-capture/{x['id']}",headers=h,json=dict(revision=x['revision'],reason='Reviewed shift',draft=d));assert r.status_code==200,r.text
    return r.json()


def test_parser_preserves_blank_pairs_rework_splits():
    d=parse_report('MD =\nBrother op.10/20 Done = 506/720\nBrother 4 = 14 (168 rework done)\nM1 Cell\nFine bore - 521048/135cc/4D - 720:330, 4D-60, 135cc-170, 521048-100')
    assert d['rows'][0]['actual'] is None and d['rows'][1]['actual'] is None
    assert d['rows'][2]['actual']==14 and d['rows'][2]['warnings']
    assert sum(x['quantity'] for x in d['rows'][3]['splits'])==330
    assert parse_report('CNC 1 - K405 - 235:190','target-actual')['rows'][0]['actual']==190


def test_real_ocr():
    text=ocr_image(read_image(picture()))
    assert '235' in text and '190' in text and 'CNC' in text,text


def test_import_replay_and_overlap(monkeypatch):
    c=TestClient(app);h=headers(c);x=prepared(c,h,monkeypatch);url=f"/api/shop-capture/{x['id']}"
    r=c.post(url+'/preview',headers=h,json={'revision':x['revision']});assert r.json()['can_confirm'],r.text
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(MachineShiftProduction))==0
    r=c.post(url+'/confirm',headers=h,json={'revision':x['revision']});assert r.status_code==200,r.text
    assert len(r.json()['receipt'])==1
    assert c.post(url+'/confirm',headers=h,json={'revision':x['revision']}).status_code==200
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(MachineShiftProduction))==1
    y=new_capture(c,h,monkeypatch,'CNC 1 = 190 (same shift)');d=x['draft'];d['text']=y['draft']['text'];d['rows'][0]['source_text']=y['draft']['rows'][0]['source_text']
    r=c.put(f"/api/shop-capture/{y['id']}",headers=h,json=dict(revision=y['revision'],reason='Repeated source',draft=d));assert r.status_code==200,r.text
    r=c.post(f"/api/shop-capture/{y['id']}/confirm",headers=h,json={'revision':r.json()['revision']});assert r.status_code==422 and 'already exists' in r.text


def test_duplicate_access_and_bad_image(monkeypatch):
    c=TestClient(app);h=headers(c);x=new_capture(c,h,monkeypatch);y=new_capture(c,h,monkeypatch)
    assert x['id']==y['id'] and y['duplicate']
    assert c.post('/api/shop-capture/upload',headers=h,files={'file':('bad.png',b'bad')}).status_code==422
    with SessionLocal() as db:
        for name,role in [('viewer',UserRole.VIEW_ONLY),('prod',UserRole.PRODUCTION)]:
            db.add(User(username=name,full_name=name,role=role,password_hash=hash_password('TestPassword123!'),must_change_password=False))
        db.commit()
    v=headers(c,'viewer','TestPassword123!');p=headers(c,'prod','TestPassword123!')
    assert c.post('/api/shop-capture/upload',headers=v,files={'file':('x.png',picture())}).status_code==403
    assert c.get(f"/api/shop-capture/{x['id']}/image",headers=p).status_code==404


def test_closed_month_stale_and_incomplete(monkeypatch):
    c=TestClient(app);h=headers(c);x=prepared(c,h,monkeypatch);url=f"/api/shop-capture/{x['id']}"
    assert c.post(url+'/confirm',headers=h,json={'revision':1}).status_code==409
    assert c.post('/api/governance/months/close',headers=h,json={'month':'2026-10-01','reason':'Approved monthly close'}).status_code==200
    r=c.post(url+'/preview',headers=h,json={'revision':x['revision']});assert not r.json()['can_confirm'] and 'closed' in str(r.json())
    assert c.post(url+'/confirm',headers=h,json={'revision':x['revision']}).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MachineShiftProduction))==0
        assert db.get(ShopCapture,x['id']).status=='draft'
    x['draft']['rows'][0]['good_count']=None
    r=c.put(url,headers=h,json=dict(revision=x['revision'],reason='Quality not supplied',draft=x['draft']));assert r.status_code==200
    r=c.post(url+'/preview',headers=h,json={'revision':r.json()['revision']});assert not r.json()['can_confirm']


def test_partial_import_preserves_evidence_and_pending_review(monkeypatch):
    c=TestClient(app);h=headers(c);x=prepared(c,h,monkeypatch);url=f"/api/shop-capture/{x['id']}"
    d=x['draft'];d['text']+='\nMD =';pending=parse_report('MD =')['rows'][0];pending['source_line']=2;d['rows'].append(pending)
    r=c.put(url,headers=h,json=dict(revision=x['revision'],reason='Retain missing quality',draft=d));assert r.status_code==200,r.text
    r=c.post(url+'/confirm',headers=h,json={'revision':r.json()['revision']});assert r.status_code==200,r.text
    x=r.json();assert x['status']=='partial' and x['draft']['rows'][0]['disposition']=='imported'
    x['draft']['rows'][0]['actual']=200
    r=c.put(url,headers=h,json=dict(revision=x['revision'],reason='Attempt imported edit',draft=x['draft']));assert r.status_code==409
    x['draft']['rows'][0]['actual']=190;x['draft']['rows'][1]['reason']='Quality figure not available'
    r=c.put(url,headers=h,json=dict(revision=x['revision'],reason='Reviewed pending quality',draft=x['draft']));assert r.status_code==200,r.text
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(MachineShiftProduction))==1


def test_machine_input_validation(monkeypatch):
    c=TestClient(app);h=headers(c);x=prepared(c,h,monkeypatch);url=f"/api/shop-capture/{x['id']}"
    for field,value,expected in [('good_count',191,'Good quantity'),('downtime_min',460,'exceed'),('ideal_cycle_time_sec',59,'effective master')]:
        d=x['draft'];old=d['rows'][0][field];d['rows'][0][field]=value
        r=c.put(url,headers=h,json=dict(revision=x['revision'],reason='Input validation check',draft=d));assert r.status_code==200,r.text
        x=r.json();r=c.post(url+'/preview',headers=h,json={'revision':x['revision']});assert not r.json()['can_confirm'] and expected in str(r.json()),r.text
        x['draft']['rows'][0][field]=old
