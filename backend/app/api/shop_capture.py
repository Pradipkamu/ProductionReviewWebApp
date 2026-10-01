import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import (ShopCapture, User, Machine, Product, RouteOperation, RouteVersion,
                      OperationMachineMap, StandardCycleTime, MachineShiftProduction)
from ..services.shop_capture import MAX_IMAGE_BYTES, read_image, ocr_image, parse_report

router = APIRouter(prefix='/shop-capture', tags=['Shop production capture'])


class CaptureRow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_line: int
    source_text: str
    label: str
    product_hint: str = ''
    actual: int | None = Field(None, ge=0, le=1000000000)
    target: int | None = Field(None, ge=0, le=1000000000)
    warnings: list[str] = []
    splits: list[dict] = []
    disposition: Literal['pending', 'machine', 'exclude', 'imported'] = 'pending'
    machine_id: int | None = None
    product_id: int | None = None
    route_operation_id: int | None = None
    shift_duration_min: Decimal | None = Field(None, gt=0, le=1440)
    planned_break_min: Decimal | None = Field(None, ge=0, le=1440)
    downtime_min: Decimal | None = Field(None, ge=0, le=1440)
    good_count: int | None = Field(None, ge=0, le=1000000000)
    ideal_cycle_time_sec: Decimal | None = Field(None, gt=0, le=86400)
    reason: str = Field('', max_length=2000)


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(max_length=50000)
    pair_order: Literal['unknown', 'target-actual', 'actual-target'] = 'unknown'
    plant: str = Field('', max_length=120)
    shop: str = Field('', max_length=120)
    production_date: str = ''
    shift: str = Field('', max_length=30)
    stated_hours: int | None = None
    rows: list[CaptureRow] = Field(max_length=1000)


class SaveDraft(BaseModel):
    revision: int
    reason: str = Field(min_length=3, max_length=2000)
    draft: Draft


class ParseText(BaseModel):
    text: str = Field(max_length=50000)
    pair_order: Literal['unknown', 'target-actual', 'actual-target'] = 'unknown'


class Revision(BaseModel):
    revision: int


def access(db, user, capture_id):
    row = db.get(ShopCapture, capture_id)
    if not row or (row.owner_id != user.id and user.role.value != 'ADMIN'):
        raise HTTPException(404, 'Capture not found')
    return row


def result(row):
    return dict(id=row.id, source_name=row.source_name, original_text=row.original_text,
                revision=row.revision, status=row.status, draft=json.loads(row.draft_json),
                receipt=json.loads(row.receipt_json), history=json.loads(row.history_json))


@router.get('')
def list_captures(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(ShopCapture).order_by(ShopCapture.id.desc()).limit(100)
    if user.role.value != 'ADMIN':
        query = query.where(ShopCapture.owner_id == user.id)
    return [dict(id=r.id, source_name=r.source_name, status=r.status, created_at=r.created_at)
            for r in db.scalars(query)]


@router.post('/parse')
def parse(payload: ParseText, user: User = Depends(get_current_user)):
    return parse_report(payload.text, payload.pair_order)


@router.post('/upload')
def upload(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    png = read_image(data)
    sha = hashlib.sha256(png).hexdigest()
    existing = db.scalar(select(ShopCapture).where(ShopCapture.owner_id == user.id, ShopCapture.file_sha256 == sha))
    if existing:
        return {**result(existing), 'duplicate': True}
    text = ocr_image(png)
    root = Path(get_settings().upload_dir) / 'shop-capture'
    root.mkdir(parents=True, exist_ok=True)
    path = root / (uuid.uuid4().hex + '.png')
    path.write_bytes(png)
    row = ShopCapture(owner_id=user.id, file_sha256=sha, source_name=(file.filename or 'image')[:260],
                      image_path=path.name, original_text=text, draft_json=json.dumps(parse_report(text)))
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return result(row)


@router.get('/{capture_id}')
def get_capture(capture_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return result(access(db, user, capture_id))


@router.get('/{capture_id}/image')
def get_image(capture_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = access(db, user, capture_id)
    path = Path(get_settings().upload_dir) / 'shop-capture' / row.image_path
    if not path.is_file():
        raise HTTPException(404, 'Source image is missing from the uploads volume')
    return FileResponse(path, media_type='image/png')


@router.put('/{capture_id}')
def save(capture_id: int, payload: SaveDraft, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = access(db, user, capture_id)
    if row.status == 'imported' or row.revision != payload.revision:
        raise HTTPException(409, 'Draft changed or was imported. Reload it before editing.')
    if not payload.reason.strip():
        raise HTTPException(422, 'Enter a review reason')
    # Source references must point to the submitted transcription, never fabricated evidence.
    lines = payload.draft.text.splitlines()
    for item in payload.draft.rows:
        if item.source_line < 1 or item.source_line > len(lines) or item.source_text != lines[item.source_line - 1]:
            raise HTTPException(422, 'Source line mismatch; re-extract the transcription')
    previous = Draft.model_validate_json(row.draft_json)
    if json.loads(row.receipt_json):
        if any(getattr(payload.draft, k) != getattr(previous, k) for k in ['plant','shop','production_date','shift']):
            raise HTTPException(409, 'Identity of a partially imported report is immutable')
        if payload.draft.text != previous.text or payload.draft.pair_order != previous.pair_order or len(payload.draft.rows) != len(previous.rows):
            raise HTTPException(409, 'Imported source evidence cannot be re-extracted; edit remaining rows only')
    for i, item in enumerate(payload.draft.rows):
        old = previous.rows[i] if i < len(previous.rows) else None
        if item.disposition == 'imported' and (not old or old.disposition != 'imported'):
            raise HTTPException(422, 'Imported status is assigned by the server')
        if old and old.disposition == 'imported' and item != old:
            raise HTTPException(409, 'Imported rows are immutable')
    history = json.loads(row.history_json)
    history.append(dict(actor_id=user.id, at=datetime.utcnow().isoformat(), reason=payload.reason,
                        revision=row.revision, before=json.loads(row.draft_json)))
    row.history_json = json.dumps(history)
    row.draft_json = payload.draft.model_dump_json()
    row.revision += 1
    db.commit()
    return result(row)


def validated_entries(db, row):
    draft = Draft.model_validate_json(row.draft_json)
    errors = []
    entries = []
    try:
        day = date.fromisoformat(draft.production_date)
    except ValueError:
        return [], ['Enter a valid production date']
    if draft.shift.strip() not in {'A', 'B', 'C'}:
        errors.append('Confirm canonical shift A, B or C to prevent duplicate shift labels')
    if not all(x.strip() for x in [draft.plant, draft.shop, draft.shift]):
        errors.append('Confirm plant, shop and shift')
    seen = set()
    for index, item in enumerate(draft.rows):
        prefix = f'Row {index + 1}: '
        if item.disposition != 'machine':
            if item.disposition == 'exclude' and not item.reason.strip():
                errors.append(prefix + 'Excluding a row requires a reason')
            continue
        if not item.reason.strip():
            errors.append(prefix + 'Confirm fresh production and source remarks in the review reason')
        if item.splits:
            errors.append(prefix + 'Mixed-product totals remain pending; separate run-time allocation is required')
        fields = ['machine_id', 'product_id', 'route_operation_id', 'actual', 'good_count',
                  'shift_duration_min', 'planned_break_min', 'downtime_min', 'ideal_cycle_time_sec']
        if any(getattr(item, key) is None for key in fields):
            errors.append(prefix + 'Complete mapping, total/good quantities, time and cycle-time inputs')
            continue
        machine = db.get(Machine, item.machine_id)
        product = db.get(Product, item.product_id)
        operation = db.get(RouteOperation, item.route_operation_id)
        route = db.get(RouteVersion, operation.route_version_id) if operation else None
        if not machine or not machine.is_active or not product or not product.is_active:
            errors.append(prefix + 'Select active machine and product masters')
        if machine and machine.department and machine.department.strip().casefold() != draft.shop.strip().casefold():
            errors.append(prefix + 'Shop must match the machine department master')
        if product and (product.plant or '').strip() != draft.plant.strip():
            errors.append(prefix + 'Product plant must match the selected plant master value')
        if not route or route.product_id != item.product_id or not operation.is_enabled or route.effective_from > day or (route.effective_to and route.effective_to < day):
            errors.append(prefix + 'Operation is outside the product route effective on this date')
        mapping = db.scalar(select(OperationMachineMap).where(OperationMachineMap.route_operation_id == item.route_operation_id,
            OperationMachineMap.machine_id == item.machine_id, OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= day, or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= day)))
        if not mapping:
            errors.append(prefix + 'Effective operation-machine mapping missing in Masters')
        cycle = db.scalar(select(StandardCycleTime).where(StandardCycleTime.route_operation_id == item.route_operation_id,
            or_(StandardCycleTime.machine_id == item.machine_id, StandardCycleTime.machine_id.is_(None)),
            StandardCycleTime.effective_from <= day, or_(StandardCycleTime.effective_to.is_(None), StandardCycleTime.effective_to >= day))
            .order_by(StandardCycleTime.machine_id.desc().nullslast(), StandardCycleTime.effective_from.desc(), StandardCycleTime.id.desc()))
        if not cycle or cycle.ideal_cycle_time_sec != item.ideal_cycle_time_sec:
            errors.append(prefix + 'Ideal cycle time must match the effective master (seconds per piece)')
        if item.good_count > item.actual:
            errors.append(prefix + 'Good quantity exceeds total quantity')
        if item.planned_break_min + item.downtime_min > item.shift_duration_min:
            errors.append(prefix + 'Breaks plus downtime exceed shift duration')
        if item.actual > 0 and item.shift_duration_min <= item.planned_break_min + item.downtime_min:
            errors.append(prefix + 'Production requires positive runtime')
        if item.machine_id in seen:
            errors.append(prefix + 'Only one machine row per shift; keep mixed-product runs pending')
        seen.add(item.machine_id)
        existing = db.scalar(select(MachineShiftProduction.id).where(MachineShiftProduction.machine_id == item.machine_id,
            MachineShiftProduction.production_date == day, MachineShiftProduction.shift == draft.shift.strip()))
        if existing:
            errors.append(prefix + f'Machine shift already exists (#{existing}); review it in Machine / OEE')
        entries.append(dict(production_date=day, shift=draft.shift.strip(), product_id=item.product_id,
            route_operation_id=item.route_operation_id, machine_id=item.machine_id, total_count=item.actual,
            good_count=item.good_count, reject_count=item.actual-item.good_count, shift_duration_min=item.shift_duration_min,
            planned_break_min=item.planned_break_min, downtime_min=item.downtime_min, ideal_cycle_time_sec=item.ideal_cycle_time_sec,
            remarks=f'Capture #{row.id}, source line {item.source_line}; shop {draft.shop}; {item.reason}'))
    if not entries:
        errors.append('Select at least one complete machine row for import; other observations may remain pending')
    return entries, errors


@router.post('/{capture_id}/preview')
def preview(capture_id: int, payload: Revision, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = access(db, user, capture_id)
    if row.status == 'imported' or payload.revision != row.revision:
        raise HTTPException(409, 'Reload the current draft')
    entries, errors = validated_entries(db, row)
    if not errors:
        try:
            # Exercise month protection without consuming authorization or saving business rows.
            with db.begin_nested() as transaction:
                db.add_all(MachineShiftProduction(**entry) for entry in entries)
                db.flush()
                transaction.rollback()
        except HTTPException as exc:
            errors.append(str(exc.detail))
    return dict(revision=row.revision, can_confirm=not errors, errors=errors, new=len(entries),
                pending=sum(x['disposition']=='pending' for x in json.loads(row.draft_json)['rows']))


@router.post('/{capture_id}/confirm')
def confirm(capture_id: int, payload: Revision, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = access(db, user, capture_id)
    if row.status == 'imported':
        return result(row)
    if payload.revision != row.revision:
        raise HTTPException(409, 'Draft changed; preview it again')
    entries, errors = validated_entries(db, row)
    if errors:
        raise HTTPException(422, '; '.join(errors))
    created = [MachineShiftProduction(**entry) for entry in entries]
    db.add_all(created)
    db.flush()  # governance checks and all business records succeed together
    draft = json.loads(row.draft_json)
    selected = [r for r in draft['rows'] if r['disposition'] == 'machine']
    receipt = json.loads(row.receipt_json)
    for item, record in zip(selected, created):
        item['disposition'] = 'imported'
        receipt.append(dict(id=record.id, source_line=item['source_line'], machine_id=record.machine_id,
                            product_id=record.product_id, date=str(record.production_date), shift=record.shift))
    row.status = 'partial' if any(r['disposition']=='pending' for r in draft['rows']) else 'imported'
    row.draft_json = json.dumps(draft)
    row.revision += 1
    row.receipt_json = json.dumps(receipt)
    history=json.loads(row.history_json)
    history.append(dict(actor_id=user.id, at=datetime.utcnow().isoformat(), event='IMPORT', receipt=json.loads(row.receipt_json)))
    row.history_json=json.dumps(history)
    db.commit()
    return result(row)
