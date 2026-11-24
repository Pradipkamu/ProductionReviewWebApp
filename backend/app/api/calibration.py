from __future__ import annotations
import json
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db

router = APIRouter(prefix="/calibration", tags=["calibration"])

EQUIPMENT_TYPES = [
    "Vernier Caliper", "Outside Micrometer", "Bore Gauge", "Height Gauge",
    "Dial Indicator", "Thread Plug / Ring Gauge", "Air Gauge", "Digital Caliper",
    "Inside Micrometer", "Depth Gauge", "Digital Indicator", "Snap Gauge",
    "Slip Gauge / Gauge Block", "Torque Wrench", "CMM", "Surface Roughness Tester",
    "Hardness Tester", "Profile Projector", "Air Gauge Setting Ring", "Plug Gauge", "Other",
]

class InstrumentIn(BaseModel):
    instrument_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    equipment_type: str
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    range_text: str | None = None
    resolution_text: str | None = None
    accuracy_text: str | None = None
    location: str | None = None
    owner_department: str | None = None
    calibration_interval_days: int = Field(default=365, ge=1, le=3650)
    criticality: str = "NORMAL"
    remarks: str | None = None
    reason: str = Field(min_length=3)

class CalibrationEventIn(BaseModel):
    event_type: str = "CALIBRATION"
    calibration_date: date
    certificate_number: str | None = None
    laboratory_name: str | None = None
    laboratory_accreditation: str | None = None
    traceability_reference: str | None = None
    result: str
    as_found: str | None = None
    as_left: str | None = None
    uncertainty: str | None = None
    certificate_uri: str | None = None
    remarks: str | None = None

class ImpactIn(BaseModel):
    period_from: date
    period_to: date
    affected_product_ids: list[int] = []
    affected_lot_references: list[str] = []
    affected_quantity: float = Field(default=0, ge=0)
    assessment: str = Field(min_length=5)
    disposition: str
    action_id: int | None = None

def _audit(db, instrument_id, action, before, after, reason, user_id, event_id=None):
    db.execute(text("""INSERT INTO calibration_audit_log
      (instrument_id,event_id,action,before_json,after_json,reason,changed_by)
      VALUES (:iid,:eid,:action,:before,:after,:reason,:uid)"""),
      dict(iid=instrument_id,eid=event_id,action=action,
           before=json.dumps(before,default=str) if before is not None else None,
           after=json.dumps(after,default=str) if after is not None else None,
           reason=reason,uid=user_id))

@router.get("/equipment-types")
def equipment_types(user=Depends(get_current_user)):
    return EQUIPMENT_TYPES

@router.get("/instruments")
def list_instruments(status: str | None = None, due_only: bool = False, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = "SELECT * FROM calibration_instruments WHERE is_active = true"
    params = {}
    if status:
        q += " AND status = :status"; params["status"] = status
    if due_only:
        q += " AND next_due_date <= :today"; params["today"] = date.today()
    q += " ORDER BY next_due_date NULLS FIRST, instrument_code"
    rows = db.execute(text(q), params).mappings().all()
    today = date.today()
    result = []
    for row in rows:
        item = dict(row)
        if item.get('next_due_date') and item['next_due_date'] < today and item['status'] == 'CALIBRATED':
            item['status'] = 'OVERDUE'
        result.append(item)
    return result

@router.post("/instruments")
def create_instrument(data: InstrumentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.equipment_type not in EQUIPMENT_TYPES:
        raise HTTPException(422, "Select a valid equipment type")
    if data.criticality not in ("NORMAL","IMPORTANT","CRITICAL"):
        raise HTTPException(422, "Invalid criticality")
    values = data.model_dump(exclude={"reason"})
    values.update(created_by=user.id)
    try:
        result = db.execute(text("""INSERT INTO calibration_instruments
          (instrument_code,name,equipment_type,manufacturer,model,serial_number,range_text,resolution_text,
           accuracy_text,location,owner_department,calibration_interval_days,criticality,remarks,created_by)
          VALUES (:instrument_code,:name,:equipment_type,:manufacturer,:model,:serial_number,:range_text,
           :resolution_text,:accuracy_text,:location,:owner_department,:calibration_interval_days,:criticality,:remarks,:created_by)
          RETURNING id"""), values)
        iid = result.scalar_one()
        _audit(db,iid,"INSTRUMENT_CREATED",None,values,data.reason,user.id)
        db.commit()
        return {"id":iid,"status":"PENDING"}
    except Exception:
        db.rollback()
        raise

@router.post("/instruments/{instrument_id}/calibration")
def record_calibration(instrument_id: int, data: CalibrationEventIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inst = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id FOR UPDATE"),{"id":instrument_id}).mappings().first()
    if not inst: raise HTTPException(404,"Instrument not found")
    if data.event_type not in ("CALIBRATION","VERIFICATION","REPAIR","ADJUSTMENT") or data.result not in ("PASS","FAIL","CONDITIONAL"):
        raise HTTPException(422,"Invalid calibration event or result")
    due = data.calibration_date + timedelta(days=int(inst["calibration_interval_days"]))
    result = db.execute(text("""INSERT INTO calibration_events
      (instrument_id,event_type,calibration_date,due_date,certificate_number,laboratory_name,
       laboratory_accreditation,traceability_reference,result,as_found,as_left,uncertainty,certificate_uri,
       remarks,performed_by,approved_by)
      VALUES (:iid,:typ,:dt,:due,:cert,:lab,:acc,:trace,:res,:found,:left,:unc,:uri,:remarks,:uid,NULL)
      RETURNING id"""),dict(iid=instrument_id,typ=data.event_type,dt=data.calibration_date,due=due,
      cert=data.certificate_number,lab=data.laboratory_name,acc=data.laboratory_accreditation,
      trace=data.traceability_reference,res=data.result,found=data.as_found,left=data.as_left,
      unc=data.uncertainty,uri=data.certificate_uri,remarks=data.remarks,uid=user.id))
    eid=result.scalar_one()
    new_status = "CALIBRATED" if data.result == "PASS" and due >= date.today() else ("OVERDUE" if data.result == "PASS" else ("FAILED" if data.result == "FAIL" else "QUARANTINED"))
    db.execute(text("""UPDATE calibration_instruments SET last_calibration_date=:dt,next_due_date=:due,
      status=:status,updated_at=now() WHERE id=:id"""),dict(dt=data.calibration_date,due=due,status=new_status,id=instrument_id))
    _audit(db,instrument_id,"CALIBRATION_RECORDED",dict(inst),data.model_dump(mode="json"),"Calibration event recorded",user.id,eid)
    db.commit()
    return {"event_id":eid,"status":new_status,"next_due_date":due}

@router.post("/events/{event_id}/impact")
def assess_impact(event_id: int, data: ImpactIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    ev=db.execute(text("SELECT * FROM calibration_events WHERE id=:id"),{"id":event_id}).mappings().first()
    if not ev: raise HTTPException(404,"Calibration event not found")
    if data.period_to < data.period_from: raise HTTPException(422,"Invalid assessment period")
    result=db.execute(text("""INSERT INTO calibration_impact_assessments
      (event_id,period_from,period_to,affected_product_ids,affected_lot_references,affected_quantity,
       assessment,disposition,action_id,assessed_by)
      VALUES (:eid,:pf,:pt,:products,:lots,:qty,:assessment,:disp,:action,:uid) RETURNING id"""),
      dict(eid=event_id,pf=data.period_from,pt=data.period_to,products=json.dumps(data.affected_product_ids),
      lots=json.dumps(data.affected_lot_references),qty=data.affected_quantity,assessment=data.assessment,
      disp=data.disposition,action=data.action_id,uid=user.id))
    aid=result.scalar_one()
    _audit(db,ev["instrument_id"],"IMPACT_ASSESSED",None,data.model_dump(mode="json"),data.assessment,user.id,event_id)
    db.commit()
    return {"id":aid}

@router.get("/audit/{instrument_id}")
def audit_history(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("SELECT * FROM calibration_audit_log WHERE instrument_id=:id ORDER BY changed_at DESC,id DESC"),{"id":instrument_id}).mappings().all()]
