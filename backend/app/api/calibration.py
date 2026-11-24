from __future__ import annotations

import json
import qrcode
from datetime import date, datetime, timedelta
from io import BytesIO
from openpyxl import Workbook, load_workbook
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pathlib import Path
import uuid
from fastapi.responses import FileResponse, StreamingResponse
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




class CalibrationLocationIn(BaseModel):
    location_code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    plant_name: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=100)
    area: str | None = None
    description: str | None = None


class InstrumentLocationTransactionIn(BaseModel):
    location_id: int
    transaction_type: str = "ISSUE"
    custodian_name: str | None = None
    issued_to: str | None = None
    purpose: str | None = None
    reason: str = Field(min_length=5)


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



IMPORT_ALIASES = {
    "instrument_code": ("instrument_code", "gauge_id", "gauge_no", "gauge_number", "gauge_code", "id", "asset_id", "tag_no", "control_no"),
    "name": ("name", "gauge_name", "instrument_name", "description", "equipment_name"),
    "equipment_type": ("equipment_type", "gauge_type", "instrument_type", "type"),
    "manufacturer": ("manufacturer", "make", "brand"),
    "model": ("model", "model_no"),
    "serial_number": ("serial_number", "serial_no", "serial", "s_no"),
    "range_text": ("range_text", "range", "measuring_range", "measurement_range"),
    "resolution_text": ("resolution_text", "resolution", "least_count"),
    "accuracy_text": ("accuracy_text", "accuracy", "permissible_error", "tolerance"),
    "location": ("location", "current_location", "gauge_location", "storage_location"),
    "home_plant": ("home_plant", "plant", "plant_name"),
    "owner_department": ("owner_department", "department", "owner", "section"),
    "owner_type": ("owner_type", "ownership"),
    "control_plan_reference": ("control_plan_reference", "control_plan", "cp_reference"),
    "special_characteristic": ("special_characteristic", "special_char", "characteristic"),
    "calibration_interval_days": ("calibration_interval_days", "calibration_interval", "interval_days", "frequency_days"),
    "last_calibration_date": ("last_calibration_date", "last_calibration", "calibration_date", "last_cal_date"),
    "next_due_date": ("next_due_date", "due_date", "calibration_due_date", "next_calibration_date"),
    "status": ("status", "gauge_status", "calibration_status"),
    "criticality": ("criticality", "risk", "criticality_level"),
    "remarks": ("remarks", "remark", "notes", "comments"),
}

def _import_header(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")

def _import_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    raise ValueError("Invalid date; use Excel date or DD-MM-YYYY")

def _parse_gauge_workbook(raw):
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Excel file exceeds the 10 MB limit")
    try:
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(422, "Unable to read workbook. Upload a valid .xlsx file.") from exc
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    headers = next(iterator, None)
    if not headers:
        raise HTTPException(422, "The selected worksheet is empty")
    normalized = [_import_header(v) for v in headers]
    mapping = {}
    for field, aliases in IMPORT_ALIASES.items():
        for idx, header in enumerate(normalized):
            if header in aliases:
                mapping[field] = idx
                break
    missing = [field for field in ("instrument_code", "name", "equipment_type") if field not in mapping]
    if missing:
        workbook.close()
        raise HTTPException(422, "Missing required columns: " + ", ".join(missing) +
                            ". Required: Gauge ID/Instrument Code, Gauge Name, Equipment Type.")
    parsed = []
    errors = []
    for row_number, cells in enumerate(iterator, start=2):
        if not cells or not any(v not in (None, "") for v in cells):
            continue
        if len(parsed) >= 5000:
            errors.append({"row": row_number, "instrument_code": None, "error": "Workbook exceeds 5,000 gauge rows"})
            break
        item = {field: (cells[idx] if idx < len(cells) else None) for field, idx in mapping.items()}
        code = str(item.get("instrument_code") or "").strip()
        name = str(item.get("name") or "").strip()
        equipment = str(item.get("equipment_type") or "").strip()
        row_errors = []
        if not code: row_errors.append("Gauge ID is required")
        if not name: row_errors.append("Gauge name is required")
        if equipment not in EQUIPMENT_TYPES:
            row_errors.append("Unknown equipment type: " + equipment)
        try:
            interval = int(item.get("calibration_interval_days") or 365)
            if interval < 1 or interval > 3650: raise ValueError()
        except (TypeError, ValueError):
            interval = 365
            row_errors.append("Calibration interval must be 1–3650 days")
        try:
            last_date = _import_date(item.get("last_calibration_date"))
            due_date = _import_date(item.get("next_due_date"))
        except ValueError as exc:
            last_date, due_date = None, None
            row_errors.append(str(exc))
        status = str(item.get("status") or "").strip().upper()
        warnings = []
        if status and status not in {"PENDING","IN_CALIBRATION","PENDING_APPROVAL","CALIBRATED","OVERDUE","FAILED","QUARANTINED","RETIRED"}:
            row_errors.append("Invalid status: " + status)
        elif status == "CALIBRATED":
            status = "PENDING_APPROVAL"
            warnings.append("Imported CALIBRATED status changed to PENDING_APPROVAL because historical calibration and independent release evidence were not imported.")
        criticality = str(item.get("criticality") or "NORMAL").strip().upper()
        if criticality not in {"NORMAL","IMPORTANT","CRITICAL"}:
            row_errors.append("Invalid criticality: " + criticality)
        owner_type = str(item.get("owner_type") or "INTERNAL").strip().upper()
        if owner_type not in {"INTERNAL","CUSTOMER","SUPPLIER","EMPLOYEE"}:
            row_errors.append("Invalid owner type: " + owner_type)
        if last_date and not due_date:
            due_date = last_date + timedelta(days=interval)
        if not status:
            status = "PENDING" if not last_date else ("OVERDUE" if due_date and due_date < date.today() else "PENDING_APPROVAL")
        clean = {
            "instrument_code": code, "name": name, "equipment_type": equipment,
            "manufacturer": str(item.get("manufacturer") or "").strip() or None,
            "model": str(item.get("model") or "").strip() or None,
            "serial_number": str(item.get("serial_number") or "").strip() or None,
            "range_text": str(item.get("range_text") or "").strip() or None,
            "resolution_text": str(item.get("resolution_text") or "").strip() or None,
            "accuracy_text": str(item.get("accuracy_text") or "").strip() or None,
            "location": str(item.get("location") or "").strip() or None,
            "home_plant": str(item.get("home_plant") or "").strip() or None,
            "owner_department": str(item.get("owner_department") or "").strip() or None,
            "owner_type": owner_type,
            "control_plan_reference": str(item.get("control_plan_reference") or "").strip() or None,
            "special_characteristic": str(item.get("special_characteristic") or "").strip() or None,
            "calibration_interval_days": interval, "last_calibration_date": last_date,
            "next_due_date": due_date, "status": status, "criticality": criticality,
            "remarks": str(item.get("remarks") or "").strip() or None,
        }
        parsed.append({"row": row_number, "data": clean, "errors": row_errors, "warnings": warnings})
    workbook.close()
    return parsed, mapping, errors

@router.get("/instruments/import/template")
def gauge_import_template(user=Depends(get_current_user)):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Gauge Register"
    headers = [
        "Gauge ID", "Gauge Name", "Equipment Type", "Manufacturer", "Model", "Serial Number",
        "Range", "Resolution", "Accuracy", "Location", "Plant", "Department", "Owner Type",
        "Control Plan Reference", "Special Characteristic", "Calibration Interval Days",
        "Last Calibration Date", "Next Due Date", "Status", "Criticality", "Remarks"
    ]
    sheet.append(headers)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{chr(64 + len(headers))}1"
    instructions = workbook.create_sheet("Instructions")
    instructions.append(["Field", "Guidance"])
    instructions.append(["Required", "Gauge ID, Gauge Name, Equipment Type"])
    instructions.append(["Date format", "Use Excel dates or DD-MM-YYYY"])
    instructions.append(["Equipment Type", "Use the exact equipment type values displayed in Calibration Management"])
    instructions.append(["Status", "PENDING, IN_CALIBRATION, PENDING_APPROVAL, CALIBRATED, OVERDUE, FAILED, QUARANTINED, RETIRED"])
    instructions.append(["Criticality", "NORMAL, IMPORTANT, CRITICAL"])
    instructions.append(["Owner Type", "INTERNAL, CUSTOMER, SUPPLIER, EMPLOYEE"])
    instructions.append(["Important", "Import adds new gauges only. Existing Gauge IDs are never overwritten."])
    instructions.append(["History", "This template imports the current register only. Historical calibration events and certificates must be imported separately."])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Gauge_Register_Import_Template.xlsx"'})

@router.post("/instruments/import")
async def import_instruments_excel(file: UploadFile = File(...), commit: bool = False,
                                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(415, "Only .xlsx Excel workbooks are supported")
    raw = await file.read(10 * 1024 * 1024 + 1)
    parsed, mapping, workbook_errors = _parse_gauge_workbook(raw)
    if not parsed:
        raise HTTPException(422, "No gauge data rows were found")
    codes = [x["data"]["instrument_code"] for x in parsed if x["data"]["instrument_code"]]
    code_counts = {}\n    for code in codes:\n        code_counts[code] = code_counts.get(code, 0) + 1\n    duplicates_in_file = {code for code, count in code_counts.items() if count > 1}
    existing = set()
    if codes:
        existing = set(db.execute(text("SELECT instrument_code FROM calibration_instruments WHERE instrument_code = ANY(:codes)"),
                                  {"codes": list(set(codes))}).scalars().all())
    for item in parsed:
        code = item["data"]["instrument_code"]
        if code in duplicates_in_file:
            item["errors"].append("Duplicate Gauge ID in uploaded workbook")
        if code in existing:
            item["errors"].append("Gauge ID already exists; existing record will not be overwritten")
    valid = [x for x in parsed if not x["errors"]]
    invalid = [x for x in parsed if x["errors"]]
    if not commit:
        return {"mode":"PREVIEW","sheet":"active worksheet","column_mapping":mapping,
                "total_rows":len(parsed),"valid_rows":len(valid),"invalid_rows":len(invalid),
                "existing_duplicates":len([x for x in parsed if "already exists" in " ".join(x["errors"])]),
                "rows":[{"row":x["row"],"instrument_code":x["data"]["instrument_code"],
                         "name":x["data"]["name"],"equipment_type":x["data"]["equipment_type"],
                         "status":x["data"]["status"],"next_due_date":x["data"]["next_due_date"],
                         "errors":x["errors"]} for x in parsed],
                "workbook_errors":workbook_errors}
    if invalid:
        raise HTTPException(409, detail={"message":"Import blocked because the workbook contains invalid or duplicate rows. Correct the file and preview again.",
                                         "invalid_rows":[{"row":x["row"],"instrument_code":x["data"]["instrument_code"],"errors":x["errors"]} for x in invalid]})
    inserted = []
    try:
        for item in valid:
            data = item["data"]
            result = db.execute(text("""INSERT INTO calibration_instruments
              (instrument_code,name,equipment_type,manufacturer,model,serial_number,range_text,resolution_text,
               accuracy_text,location,home_plant,owner_department,owner_type,control_plan_reference,
               special_characteristic,calibration_interval_days,last_calibration_date,next_due_date,status,
               criticality,remarks,created_by)
              VALUES (:instrument_code,:name,:equipment_type,:manufacturer,:model,:serial_number,:range_text,
               :resolution_text,:accuracy_text,:location,:home_plant,:owner_department,:owner_type,
               :control_plan_reference,:special_characteristic,:calibration_interval_days,:last_calibration_date,
               :next_due_date,:status,:criticality,:remarks,:created_by) RETURNING id"""),
              {**data,"created_by":user.id})
            iid = result.scalar_one()
            _audit(db, iid, "INSTRUMENT_IMPORTED", None, data,
                   "Imported from Excel gauge register", user.id)
            inserted.append(iid)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"mode":"COMMITTED","inserted":len(inserted),"instrument_ids":inserted,
            "message":"Gauge register imported. Calibration history and certificates were not fabricated."}


GAUGE_LIFECYCLE_STATUSES = {"ACTIVE", "DUE", "OVERDUE", "OUT_FOR_CALIBRATION", "OOT", "QUARANTINED", "PENDING_APPROVAL", "RETIRED"}
GAUGE_BLOCKED_STATUSES = {"DUE", "OVERDUE", "OUT_FOR_CALIBRATION", "OOT", "FAILED", "QUARANTINED", "PENDING_APPROVAL", "RETIRED"}


@router.get("/instruments/by-qr/{qr_token}")
def instrument_by_qr(qr_token: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.execute(text("""
        SELECT i.*, cl.name AS current_location_name, cl.plant_name AS current_location_plant,
               cl.department AS current_location_department
        FROM calibration_instruments i
        LEFT JOIN calibration_locations cl ON cl.id=i.current_location_id
        WHERE i.qr_token=:token
    """), {"token": qr_token}).mappings().first()
    if not row:
        raise HTTPException(404, "Gauge QR code is not recognised")
    return dict(row)


@router.get("/instruments/{instrument_id}/qr")
def instrument_qr_label(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.execute(text("SELECT instrument_code,qr_token FROM calibration_instruments WHERE id=:id"),
                     {"id": instrument_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Instrument not found")
    base = getattr(get_settings(), "public_app_url", "").rstrip("/")
    target = (base if base else "") + "/calibration?gauge=" + row["qr_token"]
    stream = BytesIO()
    qrcode.make(target).save(stream, format="PNG")
    stream.seek(0)
    return StreamingResponse(stream, media_type="image/png", headers={
        "Content-Disposition": 'attachment; filename="' + row["instrument_code"] + '_QR.png"'
    })


@router.post("/instruments/{instrument_id}/status")
def change_gauge_lifecycle_status(instrument_id: int, status: str, reason: str,
                                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    target = (status or "").strip().upper()
    if target not in GAUGE_LIFECYCLE_STATUSES:
        raise HTTPException(422, "Invalid gauge lifecycle status")
    if len((reason or "").strip()) < 5:
        raise HTTPException(422, "A reason of at least 5 characters is required")
    row = db.execute(text("SELECT * FROM calibration_instruments WHERE id=:id FOR UPDATE"),
                     {"id": instrument_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Instrument not found")
    current = row["status"]
    if current == "RETIRED" and target != "RETIRED":
        raise HTTPException(409, "Retired gauges cannot be reactivated; create a new gauge record")
    if target == "ACTIVE":
        passed = db.execute(text("""
            SELECT 1 FROM calibration_events
            WHERE instrument_id=:id AND result='PASS'
              AND event_type IN ('CALIBRATION','VERIFICATION') AND approved_by IS NOT NULL
            ORDER BY calibration_date DESC,id DESC LIMIT 1
        """), {"id": instrument_id}).first()
        if not passed:
            raise HTTPException(409, "ACTIVE requires a passed and independently approved calibration event")
        if row["next_due_date"] and row["next_due_date"] < date.today():
            raise HTTPException(409, "An overdue gauge cannot be set ACTIVE")
    db.execute(text("UPDATE calibration_instruments SET status=:status,is_active=:active,updated_at=now() WHERE id=:id"),
               {"status": target, "active": target != "RETIRED", "id": instrument_id})
    _audit(db, instrument_id, "GAUGE_STATUS_CHANGED",
           {"status": current, "is_active": row["is_active"]},
           {"status": target, "is_active": target != "RETIRED"}, reason, user.id)
    db.commit()
    return {"id": instrument_id, "previous_status": current, "status": target}


@router.get("/instruments")
def list_instruments(status: str | None = None, due_only: bool = False,
                     db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = """SELECT i.*,cl.name AS current_location_name,cl.plant_name AS current_location_plant,
                  cl.department AS current_location_department,cl.area AS current_location_area
             FROM calibration_instruments i
             LEFT JOIN calibration_locations cl ON cl.id=i.current_location_id
             WHERE i.is_active = true"""
    params = {}
    if status:
        q += " AND i.status = :status"
        params["status"] = status
    if due_only:
        q += " AND i.next_due_date <= :today"
        params["today"] = date.today()
    q += " ORDER BY i.next_due_date NULLS FIRST, i.instrument_code"
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
           accuracy_text,location,home_plant,owner_department,owner_type,control_plan_reference,special_characteristic,
           calibration_interval_days,criticality,remarks,created_by)
          VALUES (:instrument_code,:name,:equipment_type,:manufacturer,:model,:serial_number,:range_text,
           :resolution_text,:accuracy_text,:location,:home_plant,:owner_department,:owner_type,:control_plan_reference,
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
    return [dict(x) for x in db.execute(text("""SELECT id,instrument_code,name,equipment_type,location,home_plant,
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



@router.get("/locations")
def list_calibration_locations(plant: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = "SELECT * FROM calibration_locations WHERE is_active=true"
    params = {}
    if plant:
        q += " AND plant_name=:plant"
        params["plant"] = plant
    q += " ORDER BY plant_name,department,name"
    return [dict(x) for x in db.execute(text(q), params).mappings().all()]


@router.post("/locations")
def create_calibration_location(data: CalibrationLocationIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY"})
    try:
        row = db.execute(text("""
            INSERT INTO calibration_locations
              (location_code,name,plant_name,department,area,description,created_by)
            VALUES (:code,:name,:plant,:department,:area,:description,:uid)
            RETURNING id
        """), {"code": data.location_code.strip(), "name": data.name.strip(),
               "plant": data.plant_name.strip(), "department": data.department.strip(),
               "area": data.area, "description": data.description, "uid": user.id})
        location_id = row.scalar_one()
        db.commit()
        return {"id": location_id, "status": "ACTIVE"}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Location code already exists") from exc


@router.post("/instruments/{instrument_id}/location")
def issue_or_transfer_instrument(instrument_id: int, data: InstrumentLocationTransactionIn,
                                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_role(user, {"ADMIN", "MANAGEMENT", "QUALITY", "PRODUCTION"})
    if data.transaction_type not in {"ISSUE", "TRANSFER", "RETURN"}:
        raise HTTPException(422, "Invalid location transaction type")
    instrument = db.execute(text("""
        SELECT id,instrument_code,current_location_id,custodian_name,status
        FROM calibration_instruments WHERE id=:id AND is_active=true FOR UPDATE
    """), {"id": instrument_id}).mappings().first()
    if not instrument:
        raise HTTPException(404, "Instrument not found")
    if instrument["status"] in GAUGE_BLOCKED_STATUSES:
        raise HTTPException(409, "Gauge is blocked from issue/transfer while status is " + instrument["status"])
    destination = db.execute(text("""
        SELECT id,name,plant_name,department FROM calibration_locations
        WHERE id=:id AND is_active=true
    """), {"id": data.location_id}).mappings().first()
    if not destination:
        raise HTTPException(422, "Select an active issue location")
    current_id = instrument["current_location_id"]
    if data.transaction_type == "ISSUE" and current_id is not None:
        raise HTTPException(409, "Instrument is already issued. Use Transfer or Return.")
    if data.transaction_type in {"TRANSFER", "RETURN"} and current_id is None:
        raise HTTPException(409, "Instrument has not been issued yet. Use Issue.")
    if current_id == data.location_id:
        raise HTTPException(409, "Instrument is already assigned to this location")
    if data.transaction_type == "RETURN" and data.issued_to:
        raise HTTPException(422, "Return transaction cannot specify a new issued-to person")
    old = None
    if current_id:
        old = db.execute(text("SELECT name,plant_name,department FROM calibration_locations WHERE id=:id"),
                         {"id": current_id}).mappings().first()
    db.execute(text("""
        INSERT INTO calibration_location_transactions
          (instrument_id,from_location_id,to_location_id,transaction_type,custodian_name,
           issued_to,purpose,reason,recorded_by)
        VALUES (:iid,:from_id,:to_id,:type,:custodian,:issued_to,:purpose,:reason,:uid)
    """), {"iid": instrument_id, "from_id": current_id, "to_id": data.location_id,
           "type": data.transaction_type, "custodian": data.custodian_name,
           "issued_to": data.issued_to, "purpose": data.purpose,
           "reason": data.reason, "uid": user.id})
    db.execute(text("""
        UPDATE calibration_instruments
        SET current_location_id=:location_id,custodian_name=:custodian,
            location=:location_text,updated_at=now()
        WHERE id=:id
    """), {"location_id": data.location_id, "custodian": data.custodian_name,
           "location_text": " / ".join([destination["plant_name"], destination["department"], destination["name"]]),
           "id": instrument_id})
    after = {"location_id": data.location_id, "location": dict(destination),
             "custodian_name": data.custodian_name, "issued_to": data.issued_to,
             "purpose": data.purpose, "transaction_type": data.transaction_type}
    _audit(db, instrument_id, "INSTRUMENT_LOCATION_" + data.transaction_type,
           {"location_id": current_id, "location": dict(old) if old else None},
           after, data.reason, user.id)
    db.commit()
    return after


@router.get("/instruments/{instrument_id}/location-history")
def instrument_location_history(instrument_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not db.execute(text("SELECT 1 FROM calibration_instruments WHERE id=:id"), {"id": instrument_id}).first():
        raise HTTPException(404, "Instrument not found")
    return [dict(x) for x in db.execute(text("""
        SELECT t.id,t.transaction_type,t.transaction_date,t.custodian_name,t.issued_to,t.purpose,t.reason,
               f.name AS from_location,f.plant_name AS from_plant,f.department AS from_department,
               d.name AS to_location,d.plant_name AS to_plant,d.department AS to_department
        FROM calibration_location_transactions t
        LEFT JOIN calibration_locations f ON f.id=t.from_location_id
        JOIN calibration_locations d ON d.id=t.to_location_id
        WHERE t.instrument_id=:id ORDER BY t.transaction_date DESC,t.id DESC
    """), {"id": instrument_id}).mappings().all()]



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
    if home and home not in plants:
        plants.insert(0, home)
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
