from __future__ import annotations

import json
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pathlib import Path
import uuid
from fastapi.responses import FileResponse
from ..config import get_settings
from ..services.file_security import UploadSecurityError, safe_original_name, safe_path, save_limited_stream, validate_attachment_file

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
DISPOSITIONS = {"REINSPECT", "ACCEPT_JUSTIFIED", "REJECT", "NO_IMPACT", "PENDING"}


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
    home_plant: str | None = None
    owner_department: str | None = None
    owner_type: str = "INTERNAL"
    control_plan_reference: str | None = None
    special_characteristic: str | None = None
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
    laboratory_scope_reference: str | None = None
    traceability_reference: str | None = None
    result: str
    as_found: str | None = None
    as_left: str | None = None
    uncertainty: str | None = None
    certificate_uri: str | None = None
    laboratory_provider_id: int | None = None
    acceptance_criteria_id: int | None = None
    remarks: str | None = None


class ApprovalIn(BaseModel):
    reason: str = Field(min_length=5)


class ImpactIn(BaseModel):
    period_from: date
    period_to: date
    affected_product_ids: list[int] = Field(default_factory=list)
    affected_lot_references: list[str] = Field(default_factory=list)
    affected_quantity: float = Field(default=0, ge=0)
    assessment: str = Field(min_length=5)
    disposition: str
    action_id: int | None = None
    shipped_to_customer: bool = False
    customer_notified: bool = False
    customer_notification_reference: str | None = None


class MSAStudyIn(BaseModel):
    study_type: str
    measurement_system: str = Field(min_length=2)
    characteristic: str = Field(min_length=2)
    control_plan_reference: str | None = None
    study_date: date
    method_reference: str | None = None
    acceptance_criteria: str = Field(min_length=3)
    result_summary: str = Field(min_length=3)
    result: str
    customer_approval_reference: str | None = None
    instrument_ids: list[int] = Field(default_factory=list)
    remarks: str | None = None


def _audit(db, instrument_id, action, before, after, reason, user_id, event_id=None):
    db.execute(text("""INSERT INTO calibration_audit_log
      (instrument_id,event_id,action,before_json,after_json,reason,changed_by)
      VALUES (:iid,:eid,:action,:before,:after,:reason,:uid)"""),
      dict(iid=instrument_id, eid=event_id, action=action,
           before=json.dumps(before, default=str) if before is not None else None,
           after=json.dumps(after, default=str) if after is not None else None,
           reason=reason, uid=user_id))


def _require_role(user, allowed):
    if getattr(user, "role", None) not in allowed:
        raise HTTPException(403, "You do not have permission for this calibration action")


@router.get("/equipment-types")
def equipment_types(user=Depends(get_current_user)):
    return EQUIPMENT_TYPES


@router.get("/instruments")
def list_instruments(status: str | None = None, due_only: bool = False,
                     db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = "SELECT * FROM calibration_instruments WHERE is_active = true"
    params = {}
    if status:
        q += " AND status = :status"
        params["status"] = status
    if due_only:
        q += " AND next_due_date <= :today"
        params["today"] = date.today()
    q += " ORDER BY next_due_date NULLS FIRST, instrument_code"
    rows = db.execute(text(q), params).mappings().all()
    today = date.today()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("next_due_date") and item["next_due_date"] < today and item["status"] == "CALIBRATED":
            item["status"] = "OVERDUE"
        result.append(item)
    return result


@router.post("/instruments")
def create_instrument(data: InstrumentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if data.equipment_type not in EQUIPMENT_TYPES:
        raise HTTPException(422, "Select a valid equipment type")
    if data.criticality not in ("NORMAL", "IMPORTANT", "CRITICAL"):
        raise HTTPException(422, "Invalid criticality")
    if data.owner_type not in ("INTERNAL", "CUSTOMER", "SUPPLIER", "EMPLOYEE"):
        raise HTTPException(422, "Invalid instrument ownership type")
    values = data.model_dump(exclude={"reason"})
    values.update(created_by=user.id)
    try:
        result = db.execute(text("""INSERT INTO calibration_instruments
          (instrument_code,name,equipment_type,manufacturer,model,serial_number,range_text,resolution_text,
           accuracy_text,location,owner_department,owner_type,control_plan_reference,special_characteristic,
           calibration_interval_days,criticality,remarks,created_by)
          VALUES (:instrument_code,:name,:equipment_type,:manufacturer,:model,:serial_number,:range_text,
           :resolution_text,:accuracy_text,:location,:owner_department,:owner_type,:control_plan_reference,
           :special_characteristic,:calibration_interval_days,:criticality,:remarks,:created_by)
          RETURNING id"""), values)
        iid = result.scalar_one()
        _audit(db, iid, "INSTRUMENT_CREATED", None, values, data.reason, user.id)
        db.commit()
        return {"id": iid, "status": "PENDING"}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Instrument ID already exists") from exc
    except Exception:
        db.rollback()
        raise


@router.post("/instruments/{instrument_id}/calibration")
def record_calibration(instrument_id: int, data: CalibrationEventIn,
                       db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if data.calibration_date > date.today():
        raise HTTPException(422, "Calibration date cannot be in the future")
    if data.event_type not in ("CALIBRATION", "VERIFICATION", "REPAIR", "ADJUSTMENT"):
        raise HTTPException(422, "Invalid calibration event type")
    if data.result not in ("PASS", "FAIL", "CONDITIONAL"):
        raise HTTPException(422, "Invalid calibration result")
    inst = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id FOR UPDATE"),
                      {"id": instrument_id}).mappings().first()
    if not inst:
        raise HTTPException(404, "Instrument not found")
    if inst["status"] == "RETIRED":
        raise HTTPException(409, "Retired instruments cannot receive calibration events")
    due = data.calibration_date + timedelta(days=int(inst["calibration_interval_days"]))
    try:
        result = db.execute(text("""INSERT INTO calibration_events
          (instrument_id,event_type,calibration_date,due_date,certificate_number,laboratory_name,
           laboratory_accreditation,laboratory_scope_reference,traceability_reference,result,as_found,as_left,uncertainty,certificate_uri,
           laboratory_provider_id,acceptance_criteria_id,remarks,performed_by,approved_by)
          VALUES (:iid,:typ,:dt,:due,:cert,:lab,:acc,:scope,:trace,:res,:found,:left,:unc,:uri,:provider,:criteria,:remarks,:uid,NULL)
          RETURNING id"""), dict(iid=instrument_id, typ=data.event_type, dt=data.calibration_date,
          due=due, cert=data.certificate_number, lab=data.laboratory_name, acc=data.laboratory_accreditation,
          scope=data.laboratory_scope_reference, trace=data.traceability_reference, res=data.result, found=data.as_found, left=data.as_left,
          unc=data.uncertainty, uri=data.certificate_uri, provider=data.laboratory_provider_id, criteria=data.acceptance_criteria_id, remarks=data.remarks, uid=user.id))
        eid = result.scalar_one()
        # A PASS is not released for production use until an independent reviewer approves it.
        new_status = ("PENDING_APPROVAL" if data.result == "PASS" and data.event_type in ("CALIBRATION", "VERIFICATION")
                      else ("FAILED" if data.result == "FAIL" else "QUARANTINED"))
        db.execute(text("""UPDATE calibration_instruments SET last_calibration_date=:dt,next_due_date=:due,
          status=:status,updated_at=now() WHERE id=:id"""),
          dict(dt=data.calibration_date, due=due, status=new_status, id=instrument_id))
        _audit(db, instrument_id, "CALIBRATION_RECORDED", dict(inst),
               data.model_dump(mode="json"), "Calibration event recorded; release approval required", user.id, eid)
        db.commit()
        return {"event_id": eid, "status": new_status, "next_due_date": due}
    except Exception:
        db.rollback()
        raise


@router.get("/instruments/{instrument_id}/events")
def instrument_events(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("""SELECT * FROM calibration_events
        WHERE instrument_id=:id ORDER BY calibration_date DESC,id DESC"""),
        {"id": instrument_id}).mappings().all()]


@router.post("/events/{event_id}/approve")
def approve_calibration_event(event_id: int, data: ApprovalIn,
                              db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    ev = db.execute(text("""SELECT e.*,i.status AS instrument_status,i.calibration_interval_days
        FROM calibration_events e JOIN calibration_instruments i ON i.id=e.instrument_id
        WHERE e.id=:id FOR UPDATE OF e,i"""), {"id": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Calibration event not found")
    if ev["performed_by"] == user.id:
        raise HTTPException(403, "The person who performed the calibration cannot approve it")
    if ev["approved_by"] is not None:
        raise HTTPException(409, "Calibration event is already approved")
    latest_event_id = db.execute(text("SELECT max(id) FROM calibration_events WHERE instrument_id=:iid"),
                                 {"iid": ev["instrument_id"]}).scalar()
    if latest_event_id != event_id:
        raise HTTPException(409, "Only the latest calibration event can release this instrument")
    if ev["result"] != "PASS" or ev["event_type"] not in ("CALIBRATION", "VERIFICATION"):
        raise HTTPException(409, "Only a passing calibration or verification can be released")
    prior_bad = db.execute(text("""SELECT id FROM calibration_events
        WHERE instrument_id=:iid AND id<>:eid AND result IN ('FAIL','CONDITIONAL')
        ORDER BY calibration_date DESC,id DESC LIMIT 1"""),
        {"iid": ev["instrument_id"], "eid": event_id}).scalar()
    if prior_bad:
        assessed = db.execute(text("SELECT 1 FROM calibration_impact_assessments WHERE event_id=:eid LIMIT 1"),
                              {"eid": prior_bad}).scalar()
        unresolved = db.execute(text("""SELECT 1 FROM calibration_impact_assessments
            WHERE event_id=:eid AND disposition='PENDING' LIMIT 1"""), {"eid": prior_bad}).scalar()
        if not assessed or unresolved:
            raise HTTPException(409, "Complete the previous out-of-tolerance product impact assessment before release")
    due = ev["due_date"]
    status = "CALIBRATED" if due and due >= date.today() else "OVERDUE"
    db.execute(text("UPDATE calibration_events SET approved_by=:uid,approval_reason=:reason,approved_at=now() WHERE id=:id"),
               {"uid": user.id, "reason": data.reason, "id": event_id})
    db.execute(text("UPDATE calibration_instruments SET status=:status,updated_at=now() WHERE id=:iid"),
               {"status": status, "iid": ev["instrument_id"]})
    _audit(db, ev["instrument_id"], "CALIBRATION_APPROVED", None,
           {"event_id": event_id, "approved_by": user.id, "status": status}, data.reason, user.id, event_id)
    db.commit()
    return {"event_id": event_id, "status": status, "approved_by": user.id}


@router.post("/events/{event_id}/impact")
def assess_impact(event_id: int, data: ImpactIn,
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    ev = db.execute(text("SELECT * FROM calibration_events WHERE id=:id"),
                    {"id": event_id}).mappings().first()
    if not ev:
        raise HTTPException(404, "Calibration event not found")
    if data.period_to < data.period_from:
        raise HTTPException(422, "Invalid assessment period")
    if data.disposition not in DISPOSITIONS:
        raise HTTPException(422, "Invalid product impact disposition")
    if data.shipped_to_customer and (not data.customer_notified or not data.customer_notification_reference):
        raise HTTPException(422, "For shipped suspect product, record customer notification and its reference")
    if data.disposition == "NO_IMPACT" and len(data.assessment.strip()) < 10:
        raise HTTPException(422, "Document objective evidence supporting the no-impact conclusion")
    if data.disposition == "ACCEPT_JUSTIFIED" and len(data.assessment.strip()) < 20:
        raise HTTPException(422, "Document the technical justification and approval basis for acceptance")
    if data.shipped_to_customer and (not data.customer_notified or not data.customer_notification_reference):
        raise HTTPException(422, "Customer notification is required for shipped suspect product requiring action")
    result = db.execute(text("""INSERT INTO calibration_impact_assessments
      (event_id,period_from,period_to,affected_product_ids,affected_lot_references,affected_quantity,
       assessment,disposition,action_id,assessed_by,shipped_to_customer,customer_notified,customer_notification_reference)
      VALUES (:eid,:pf,:pt,:products,:lots,:qty,:assessment,:disp,:action,:uid,:shipped,:notified,:notification_ref)
      RETURNING id"""), dict(eid=event_id, pf=data.period_from, pt=data.period_to,
      products=json.dumps(data.affected_product_ids), lots=json.dumps(data.affected_lot_references),
      qty=data.affected_quantity, assessment=data.assessment, disp=data.disposition,
      action=data.action_id, uid=user.id, shipped=data.shipped_to_customer,
      notified=data.customer_notified, notification_ref=data.customer_notification_reference))
    aid = result.scalar_one()
    _audit(db, ev["instrument_id"], "IMPACT_ASSESSED", None, data.model_dump(mode="json"),
           data.assessment, user.id, event_id)
    db.commit()
    return {"id": aid}


@router.get("/events/{event_id}/impact")
def list_impact_assessments(event_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("""SELECT * FROM calibration_impact_assessments
        WHERE event_id=:id ORDER BY assessed_at DESC,id DESC"""), {"id": event_id}).mappings().all()]


@router.get("/msa")
def list_msa_studies(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("SELECT * FROM calibration_msa_studies ORDER BY study_date DESC,id DESC")).mappings().all()]


@router.post("/msa")
def create_msa_study(data: MSAStudyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if data.study_date > date.today():
        raise HTTPException(422, "MSA study date cannot be in the future")
    if data.study_type not in ("GAGE_RR", "BIAS", "LINEARITY", "STABILITY", "OTHER"):
        raise HTTPException(422, "Invalid MSA study type")
    if data.result not in ("ACCEPTABLE", "UNACCEPTABLE", "CONDITIONAL", "CUSTOMER_APPROVED_ALTERNATIVE"):
        raise HTTPException(422, "Invalid MSA result")
    if data.result == "CUSTOMER_APPROVED_ALTERNATIVE" and not data.customer_approval_reference:
        raise HTTPException(422, "Customer approval evidence is required for an alternative MSA method")
    for iid in data.instrument_ids:
        exists = db.execute(text("SELECT 1 FROM calibration_instruments WHERE id=:id AND is_active=true"),
                            {"id": iid}).scalar()
        if not exists:
            raise HTTPException(422, f"Unknown instrument ID: {iid}")
    values = data.model_dump()
    result = db.execute(text("""INSERT INTO calibration_msa_studies
      (study_type,measurement_system,characteristic,control_plan_reference,study_date,method_reference,
       acceptance_criteria,result_summary,result,customer_approval_reference,instrument_ids,remarks,created_by)
      VALUES (:study_type,:measurement_system,:characteristic,:control_plan_reference,:study_date,:method_reference,
       :acceptance_criteria,:result_summary,:result,:customer_approval_reference,:instrument_ids,:remarks,:created_by)
      RETURNING id"""), {**values, "instrument_ids": json.dumps(data.instrument_ids), "created_by": user.id})
    sid = result.scalar_one()
    db.commit()
    return {"id": sid}


@router.get("/audit/{instrument_id}")
def audit_history(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("""SELECT * FROM calibration_audit_log
      WHERE instrument_id=:id ORDER BY changed_at DESC,id DESC"""),
      {"id": instrument_id}).mappings().all()]

@router.get("/approvals/pending")
def pending_calibration_approvals(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    return [dict(x) for x in db.execute(text("""SELECT e.*,i.instrument_code,i.name AS instrument_name,
        i.status AS instrument_status FROM calibration_events e
        JOIN calibration_instruments i ON i.id=e.instrument_id
        WHERE e.result='PASS' AND e.event_type IN ('CALIBRATION','VERIFICATION')
          AND e.approved_by IS NULL
        ORDER BY e.calibration_date,e.id""")).mappings().all()]


@router.post("/instruments/{instrument_id}/retire")
def retire_instrument(instrument_id: int, reason: str,
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if len(reason.strip()) < 5:
        raise HTTPException(422, "Retirement reason must be at least 5 characters")
    inst = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id FOR UPDATE"),
                      {"id": instrument_id}).mappings().first()
    if not inst:
        raise HTTPException(404, "Instrument not found")
    if inst["status"] == "RETIRED":
        raise HTTPException(409, "Instrument is already retired")
    db.execute(text("UPDATE calibration_instruments SET status='RETIRED',is_active=false,updated_at=now() WHERE id=:id"),
               {"id": instrument_id})
    _audit(db, instrument_id, "INSTRUMENT_RETIRED", dict(inst), {"status":"RETIRED","is_active":False},
           reason, user.id)
    db.commit()
    return {"id": instrument_id, "status": "RETIRED"}


@router.get("/compliance-summary")
def calibration_compliance_summary(db: Session = Depends(get_db), user=Depends(get_current_user)):
    today = date.today()
    row = db.execute(text("""SELECT
        count(*) FILTER (WHERE is_active) AS active_total,
        count(*) FILTER (WHERE is_active AND next_due_date < :today AND status NOT IN ('RETIRED','FAILED','QUARANTINED')) AS overdue,
        count(*) FILTER (WHERE is_active AND status='PENDING_APPROVAL') AS pending_approval,
        count(*) FILTER (WHERE is_active AND status IN ('FAILED','QUARANTINED')) AS blocked,
        count(*) FILTER (WHERE is_active AND next_due_date IS NULL) AS never_calibrated
        FROM calibration_instruments"""), {"today": today}).mappings().one()
    return dict(row)

@router.get("/due-schedule")
def calibration_due_schedule(days: int = 30, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if days < 0 or days > 365:
        raise HTTPException(422, "Schedule horizon must be between 0 and 365 days")
    today = date.today()
    return [dict(x) for x in db.execute(text("""SELECT id,instrument_code,name,equipment_type,location,
        next_due_date,status,criticality,owner_department
        FROM calibration_instruments WHERE is_active=true
          AND (next_due_date IS NULL OR next_due_date <= :horizon)
        ORDER BY next_due_date NULLS FIRST,criticality DESC,instrument_code"""),
        {"horizon": today + timedelta(days=days)}).mappings().all()]


class LaboratoryProviderIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    accreditation_body: str | None = None
    accreditation_number: str | None = None
    accreditation_valid_to: date | None = None
    iso_iec_17025: bool = False
    scope_reference: str | None = None
    scope_parameters: str | None = None
    active: bool = True
    remarks: str | None = None


class AcceptanceCriteriaIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    equipment_type: str
    parameter: str | None = None
    range_text: str | None = None
    permissible_error: str = Field(min_length=1)
    max_uncertainty: str | None = None
    tur_requirement: str | None = None
    decision_rule: str = "SIMPLE_ACCEPTANCE"
    source_type: str = "INTERNAL_QMS"
    source_reference: str | None = None
    effective_from: date
    effective_to: date | None = None
    approval_status: str = "DRAFT"
    approved_by: str | None = None
    remarks: str | None = None


@router.get("/laboratories")
def list_laboratories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [dict(x) for x in db.execute(text("SELECT * FROM calibration_laboratory_providers WHERE active=true ORDER BY name")).mappings().all()]


@router.post("/laboratories")
def create_laboratory(data: LaboratoryProviderIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    values = data.model_dump()
    values["uid"] = user.id
    pid = db.execute(text("""INSERT INTO calibration_laboratory_providers
      (name,address,contact_person,email,phone,accreditation_body,accreditation_number,accreditation_valid_to,
       iso_iec_17025,scope_reference,scope_parameters,active,remarks,created_by)
      VALUES (:name,:address,:contact_person,:email,:phone,:accreditation_body,:accreditation_number,:accreditation_valid_to,
       :iso_iec_17025,:scope_reference,:scope_parameters,:active,:remarks,:uid) RETURNING id"""), values).scalar_one()
    db.commit()
    return {"id": pid}


@router.get("/acceptance-criteria")
def list_acceptance_criteria(equipment_type: str | None = None, approved_only: bool = True,
                             db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = "SELECT * FROM calibration_acceptance_criteria WHERE (effective_to IS NULL OR effective_to >= :today)"
    p = {"today": date.today()}
    if equipment_type:
        q += " AND equipment_type=:equipment_type"
        p["equipment_type"] = equipment_type
    if approved_only:
        q += " AND approval_status='APPROVED'"
    q += " ORDER BY equipment_type,name"
    return [dict(x) for x in db.execute(text(q), p).mappings().all()]


@router.post("/acceptance-criteria")
def create_acceptance_criteria(data: AcceptanceCriteriaIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if data.equipment_type not in EQUIPMENT_TYPES:
        raise HTTPException(422, "Select a valid equipment type")
    if data.decision_rule not in ("SIMPLE_ACCEPTANCE", "GUARD_BAND", "CUSTOMER_RULE"):
        raise HTTPException(422, "Invalid decision rule")
    if data.source_type not in ("INTERNAL_QMS", "CUSTOMER", "DRAWING", "OEM", "STANDARD"):
        raise HTTPException(422, "Invalid criteria source")
    if data.approval_status not in ("DRAFT", "APPROVED", "OBSOLETE"):
        raise HTTPException(422, "Invalid approval status")
    values = data.model_dump()
    values["uid"] = user.id
    cid = db.execute(text("""INSERT INTO calibration_acceptance_criteria
      (name,equipment_type,parameter,range_text,permissible_error,max_uncertainty,tur_requirement,decision_rule,
       source_type,source_reference,effective_from,effective_to,approval_status,approved_by,remarks,created_by)
      VALUES (:name,:equipment_type,:parameter,:range_text,:permissible_error,:max_uncertainty,:tur_requirement,:decision_rule,
       :source_type,:source_reference,:effective_from,:effective_to,:approval_status,:approved_by,:remarks,:uid) RETURNING id"""),
      values).scalar_one()
    db.commit()
    return {"id": cid}


@router.post("/events/{event_id}/certificate")
def upload_calibration_certificate(event_id: int, file: UploadFile = File(...),
                                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    if not db.execute(text("SELECT id FROM calibration_events WHERE id=:id"), {"id": event_id}).first():
        raise HTTPException(404, "Calibration event not found")
    settings = get_settings()
    original = safe_original_name(file.filename, "calibration-certificate")
    ext = Path(original).suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(422, "Calibration certificate must be PDF or an image")
    target = safe_path(Path(settings.attachments_dir) / "calibration" / str(event_id), uuid.uuid4().hex + ext)
    try:
        size, digest = save_limited_stream(file.file, target, settings.attachment_max_mb * 1024 * 1024)
        mime = validate_attachment_file(target, original, settings.attachment_extension_set, settings.office_max_uncompressed_mb * 1024 * 1024)
    except UploadSecurityError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    db.execute(text("""UPDATE calibration_events SET certificate_file_path=:path,certificate_file_name=:name,
      certificate_mime_type=:mime,certificate_size_bytes=:size,certificate_sha256=:sha WHERE id=:id"""),
      {"path": str(target), "name": original, "mime": mime, "size": size, "sha": digest, "id": event_id})
    db.commit()
    return {"event_id": event_id, "file_name": original, "size_bytes": size, "sha256": digest}


@router.get("/events/{event_id}/certificate")
def download_calibration_certificate(event_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.execute(text("""SELECT certificate_file_path,certificate_file_name,certificate_mime_type
      FROM calibration_events WHERE id=:id"""), {"id": event_id}).mappings().first()
    if not row or not row["certificate_file_path"]:
        raise HTTPException(404, "No certificate attached to this calibration event")
    path = Path(row["certificate_file_path"]).resolve()
    base = (Path(get_settings().attachments_dir) / "calibration").resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "Certificate file is unavailable")
    return FileResponse(path, media_type=row["certificate_mime_type"] or "application/octet-stream",
                        filename=row["certificate_file_name"] or "calibration-certificate")


class InstrumentScopeIn(BaseModel):
    plants: list[str] = Field(default_factory=list)
    home_plant: str | None = None
    product_ids: list[int] = Field(default_factory=list)
    route_operation_ids: list[int] = Field(default_factory=list)
    machine_ids: list[int] = Field(default_factory=list)
    reason: str = Field(min_length=5)


@router.get("/scope-options")
def calibration_scope_options(db: Session = Depends(get_db), user=Depends(get_current_user)):
    plants = [x[0] for x in db.execute(text("""
        SELECT plant FROM products WHERE plant IS NOT NULL AND trim(plant) <> ''
        UNION SELECT plant FROM machines WHERE plant IS NOT NULL AND trim(plant) <> ''
        UNION SELECT plant FROM working_calendar WHERE plant IS NOT NULL AND trim(plant) <> ''
        ORDER BY 1
    """)).all()]
    products = [dict(x) for x in db.execute(text("""
        SELECT id,code,name,plant FROM products WHERE is_active=true ORDER BY plant,code
    """)).mappings().all()]
    operations = [dict(x) for x in db.execute(text("""
        SELECT ro.id AS route_operation_id, p.id AS product_id, p.code AS product_code,
               p.name AS product_name, o.id AS operation_id, o.code AS operation_code,
               o.name AS operation_name, ro.sequence_no
        FROM route_operations ro JOIN route_versions rv ON rv.id=ro.route_version_id
        JOIN products p ON p.id=rv.product_id JOIN operations o ON o.id=ro.operation_id
        WHERE rv.is_active=true AND p.is_active=true AND o.is_active=true
        ORDER BY p.code,ro.sequence_no
    """)).mappings().all()]
    machines = [dict(x) for x in db.execute(text("""
        SELECT id,code,name,plant,department FROM machines WHERE is_active=true ORDER BY plant,code
    """)).mappings().all()]
    return {"plants": plants, "products": products, "operations": operations, "machines": machines}


@router.get("/instruments/{instrument_id}/scope")
def get_instrument_scope(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not db.execute(text("SELECT 1 FROM calibration_instruments WHERE id=:id"), {"id": instrument_id}).first():
        raise HTTPException(404, "Instrument not found")
    plants = [x[0] for x in db.execute(text("""
        SELECT plant_name FROM calibration_instrument_plants
        WHERE instrument_id=:id ORDER BY is_home DESC,plant_name
    """), {"id": instrument_id}).all()]
    products = [x[0] for x in db.execute(text("""
        SELECT product_id FROM calibration_instrument_products WHERE instrument_id=:id ORDER BY product_id
    """), {"id": instrument_id}).all()]
    operations = [x[0] for x in db.execute(text("""
        SELECT route_operation_id FROM calibration_instrument_operations WHERE instrument_id=:id ORDER BY route_operation_id
    """), {"id": instrument_id}).all()]
    machines = [x[0] for x in db.execute(text("""
        SELECT machine_id FROM calibration_instrument_machines WHERE instrument_id=:id ORDER BY machine_id
    """), {"id": instrument_id}).all()]
    home = db.execute(text("SELECT home_plant FROM calibration_instruments WHERE id=:id"), {"id": instrument_id}).scalar()
    return {"home_plant": home, "plants": plants, "product_ids": products,
            "route_operation_ids": operations, "machine_ids": machines}


@router.put("/instruments/{instrument_id}/scope")
def save_instrument_scope(instrument_id: int, data: InstrumentScopeIn,
                          db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    inst = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id FOR UPDATE"),
                      {"id": instrument_id}).mappings().first()
    if not inst:
        raise HTTPException(404, "Instrument not found")
    plants = list(dict.fromkeys(x.strip() for x in data.plants if x and x.strip()))
    home = data.home_plant.strip() if data.home_plant else None
    if home and home not in plants:
        plants.append(home)
    if len(plants) > 50 or len(set(data.product_ids)) != len(data.product_ids) or len(set(data.route_operation_ids)) != len(data.route_operation_ids) or len(set(data.machine_ids)) != len(data.machine_ids):
        raise HTTPException(422, "Duplicate or excessive scope selections")
    checks = [("products", data.product_ids), ("route_operations", data.route_operation_ids), ("machines", data.machine_ids)]
    for table, ids in checks:
        for record_id in ids:
            if not db.execute(text(f"SELECT 1 FROM {table} WHERE id=:id"), {"id": record_id}).first():
                raise HTTPException(422, f"Unknown {table.replace('_',' ')} ID: {record_id}")
    before = {"home_plant": inst["home_plant"]}
    for table in ("calibration_instrument_plants", "calibration_instrument_products",
                  "calibration_instrument_operations", "calibration_instrument_machines"):
        db.execute(text(f"DELETE FROM {table} WHERE instrument_id=:id"), {"id": instrument_id})
    for plant in plants:
        db.execute(text("""INSERT INTO calibration_instrument_plants
            (instrument_id,plant_name,is_home,created_by) VALUES (:id,:plant,:home,:uid)"""),
            {"id": instrument_id, "plant": plant, "home": plant == home, "uid": user.id})
    for pid in data.product_ids:
        db.execute(text("INSERT INTO calibration_instrument_products (instrument_id,product_id,created_by) VALUES (:id,:value,:uid)"),
                   {"id": instrument_id, "value": pid, "uid": user.id})
    for oid in data.route_operation_ids:
        db.execute(text("INSERT INTO calibration_instrument_operations (instrument_id,route_operation_id,created_by) VALUES (:id,:value,:uid)"),
                   {"id": instrument_id, "value": oid, "uid": user.id})
    for mid in data.machine_ids:
        db.execute(text("INSERT INTO calibration_instrument_machines (instrument_id,machine_id,created_by) VALUES (:id,:value,:uid)"),
                   {"id": instrument_id, "value": mid, "uid": user.id})
    db.execute(text("UPDATE calibration_instruments SET home_plant=:plant,updated_at=now() WHERE id=:id"),
               {"plant": home, "id": instrument_id})
    after = {"home_plant": home, "plants": plants, "product_ids": data.product_ids,
             "route_operation_ids": data.route_operation_ids, "machine_ids": data.machine_ids}
    _audit(db, instrument_id, "INSTRUMENT_SCOPE_UPDATED", before, after, data.reason, user.id)
    db.commit()
    return after


@router.get("/reports/register")
def calibration_register_report(plant: str | None = None, product_id: int | None = None,
                                 route_operation_id: int | None = None, machine_id: int | None = None,
                                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = """
      SELECT DISTINCT i.id,i.instrument_code,i.name,i.equipment_type,i.home_plant,i.owner_department,
        i.owner_type,i.location,i.range_text,i.resolution_text,i.criticality,i.status,
        i.last_calibration_date,i.next_due_date,i.calibration_interval_days,
        CASE WHEN i.next_due_date IS NULL THEN 'NEVER_CALIBRATED'
             WHEN i.next_due_date < CURRENT_DATE THEN 'OVERDUE'
             WHEN i.next_due_date <= CURRENT_DATE + 30 THEN 'DUE_SOON'
             ELSE i.status END AS due_status
      FROM calibration_instruments i
      LEFT JOIN calibration_instrument_plants ip ON ip.instrument_id=i.id
      LEFT JOIN calibration_instrument_products ixp ON ixp.instrument_id=i.id
      LEFT JOIN calibration_instrument_operations ixo ON ixo.instrument_id=i.id
      LEFT JOIN calibration_instrument_machines ixm ON ixm.instrument_id=i.id
      WHERE i.is_active=true
    """
    params = {}
    for key, col, value in (("plant","COALESCE(ip.plant_name,i.home_plant)",plant),
                            ("product_id","ixp.product_id",product_id),
                            ("route_operation_id","ixo.route_operation_id",route_operation_id),
                            ("machine_id","ixm.machine_id",machine_id)):
        if value is not None:
            q += f" AND {col} = :{key}"
            params[key] = value
    q += " ORDER BY i.home_plant,i.instrument_code"
    return [dict(x) for x in db.execute(text(q), params).mappings().all()]


@router.get("/instruments/{instrument_id}/history-card")
def calibration_history_card(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    instrument = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id"),
                             {"id": instrument_id}).mappings().first()
    if not instrument:
        raise HTTPException(404, "Instrument not found")
    scope = get_instrument_scope(instrument_id, db, user)
    events = [dict(x) for x in db.execute(text("""
      SELECT e.*,lp.name AS provider_name,ac.name AS criteria_name,ac.permissible_error,
             ac.max_uncertainty,ac.decision_rule,ac.source_reference
      FROM calibration_events e
      LEFT JOIN calibration_laboratory_providers lp ON lp.id=e.laboratory_provider_id
      LEFT JOIN calibration_acceptance_criteria ac ON ac.id=e.acceptance_criteria_id
      WHERE e.instrument_id=:id ORDER BY e.calibration_date DESC,e.id DESC
    """), {"id": instrument_id}).mappings().all()]
    return {"instrument": dict(instrument), "scope": scope, "events": events}
