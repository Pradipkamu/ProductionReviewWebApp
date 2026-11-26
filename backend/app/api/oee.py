from ..time_utils import UTCTimestamp
from datetime import date, datetime
import json
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Body
from pydantic import BaseModel, Field, ValidationError
from io import BytesIO
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import ActionStatus, OEEComponent, Priority, SourceType
from ..models import (
    Action, ActionContext, ActionHistory, ActionWhyWhy, LossCategory, Machine,
    MachineLossEvent, MachineShiftProduction, Operation, OperationMachineMap, Personnel,
    Product, ReviewActionLink, ReviewSession, RouteOperation, RouteVersion,
    StandardCycleTime, User, GovernanceAudit, DailyRequirement,
    MachineCapacitySetting, MachineMonthlyAllocation, WorkingCalendar,
)
from ..schemas import LossEventCreate, MachineEntryCreate, OEEEntryWithLossesCreate
from ..services.oee import aggregate_oee_entries, calculate_oee
from ..services.filtering import csv_ints, csv_strings

router = APIRouter(prefix="/oee", tags=["oee"])


MAX_OEE_BULK_ENTRIES = 1000
MAX_OEE_BULK_LOSSES_PER_ENTRY = 30
MAX_OEE_BULK_LOSS_ROWS = MAX_OEE_BULK_ENTRIES * MAX_OEE_BULK_LOSSES_PER_ENTRY


def _oee_bulk_entry_count_error(entry_count: int) -> str | None:
    if entry_count > MAX_OEE_BULK_ENTRIES:
        return (f"Workbook contains {entry_count} validated entries; the maximum is "
                f"{MAX_OEE_BULK_ENTRIES}. Split the workbook into smaller batches.")
    return None


def _validate_oee_bulk_commit_entries(items) -> None:
    if not isinstance(items, list) or not items:
        raise HTTPException(422, f"Import must contain between 1 and {MAX_OEE_BULK_ENTRIES} validated entries")
    limit_error = _oee_bulk_entry_count_error(len(items))
    if limit_error:
        raise HTTPException(422, limit_error)


def _validate_oee_bulk_loss_events(losses) -> None:
    if len(losses or []) > MAX_OEE_BULK_LOSSES_PER_ENTRY:
        raise HTTPException(422,
            f"Each OEE entry may contain no more than {MAX_OEE_BULK_LOSSES_PER_ENTRY} loss events")


class OEEActionCreate(BaseModel):
    owner_id: int | None = None
    due_at: UTCTimestamp | None = None
    priority: Priority = Priority.HIGH
    action_description: str = "Contain the loss, complete standard Why-Why analysis and implement corrective action"
    target_oee: Decimal = Field(default=Decimal("0.85"), ge=0, le=1)


class OEESummaryActionCreate(OEEActionCreate):
    production_date: date
    shift: str
    product_id: int
    route_operation_id: int
    machine_id: int


def _context(db: Session, product_id: int, route_operation_id: int, machine_id: int, on_date: date) -> dict:
    product = db.get(Product, product_id)
    machine = db.get(Machine, machine_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not machine or not machine.is_active:
        raise HTTPException(422, "Select an active machine")
    route_row = db.execute(
        select(RouteOperation, RouteVersion, Operation)
        .join(RouteVersion, RouteVersion.id == RouteOperation.route_version_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.id == route_operation_id, RouteVersion.product_id == product_id)
    ).first()
    if not route_row:
        raise HTTPException(422, "Selected operation does not belong to the selected product")
    route_operation, route_version, operation = route_row
    if not route_operation.is_enabled or not route_version.is_active:
        raise HTTPException(422, "Selected product operation is inactive")
    if route_version.effective_from > on_date or (route_version.effective_to and route_version.effective_to < on_date):
        raise HTTPException(422, "Selected operation is not effective on the production date")

    maps = db.scalars(
        select(OperationMachineMap).where(
            OperationMachineMap.route_operation_id == route_operation_id,
            OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= on_date,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= on_date),
        ).order_by(OperationMachineMap.priority, OperationMachineMap.machine_id)
    ).all()
    allowed_machine_ids = [x.machine_id for x in maps]
    warnings: list[str] = []
    if allowed_machine_ids and machine_id not in allowed_machine_ids:
        raise HTTPException(422, "Machine is not mapped to this product operation for the selected date")
    if not allowed_machine_ids:
        warnings.append("Machine mapping is missing for this product operation")

    cycle = db.scalar(
        select(StandardCycleTime).where(
            StandardCycleTime.route_operation_id == route_operation_id,
            or_(StandardCycleTime.machine_id == machine_id, StandardCycleTime.machine_id.is_(None)),
            StandardCycleTime.effective_from <= on_date,
            or_(StandardCycleTime.effective_to.is_(None), StandardCycleTime.effective_to >= on_date),
        ).order_by(StandardCycleTime.machine_id.is_(None), StandardCycleTime.effective_from.desc(), StandardCycleTime.id.desc())
    )
    if not cycle:
        warnings.append("Effective ideal cycle time is missing")
    return {
        "product": product, "machine": machine, "route_operation": route_operation,
        "operation": operation, "cycle": cycle, "warnings": warnings,
        "allowed_machine_ids": allowed_machine_ids,
    }


def _prepare_entry(db: Session, payload: MachineEntryCreate) -> tuple[dict, dict]:
    person = db.get(Personnel, payload.operator_id)
    if not person or not person.is_active:
        raise HTTPException(422, "Select an active person from the Personnel Master")

    context = _context(db, payload.product_id, payload.route_operation_id, payload.machine_id, payload.production_date)
    data = payload.model_dump()
    cycle = context["cycle"]
    if cycle:
        master_cycle = Decimal(cycle.ideal_cycle_time_sec)
        if payload.ideal_cycle_time_sec > 0 and payload.ideal_cycle_time_sec != master_cycle:
            context["warnings"].append("Entered cycle time was replaced by the effective master cycle time")
        data["ideal_cycle_time_sec"] = master_cycle
    elif payload.ideal_cycle_time_sec <= 0:
        raise HTTPException(422, "Effective ideal cycle time is missing; add it in Masters before calculating OEE")
    if payload.total_count > payload.good_count + payload.reject_count:
        context["warnings"].append("Total count is not fully classified as good or reject")
    return data, context


def _entry_json(row: MachineShiftProduction, context: dict | None = None) -> dict:
    result = {
        "id": row.id, "production_date": row.production_date, "shift": row.shift,
        "product_id": row.product_id, "route_operation_id": row.route_operation_id,
        "machine_id": row.machine_id, "operator_id": row.operator_id,
        "operator_name": row.operator.full_name if row.operator else None, "shift_duration_min": float(row.shift_duration_min),
        "planned_break_min": float(row.planned_break_min), "downtime_min": float(row.downtime_min),
        "total_count": float(row.total_count), "good_count": float(row.good_count),
        "reject_count": float(row.reject_count), "ideal_cycle_time_sec": float(row.ideal_cycle_time_sec),
        "remarks": row.remarks,
        **calculate_oee(row.shift_duration_min, row.planned_break_min, row.downtime_min,
                        row.total_count, row.good_count, row.ideal_cycle_time_sec),
    }
    if context:
        result.update({
            "product": context["product"].name, "machine": context["machine"].code,
            "operation": context["operation"].name, "data_quality_warnings": context["warnings"],
        })
    return result



def _oee_workbook_masters(db: Session) -> dict:
    products = db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name)).all()
    machines = db.scalars(select(Machine).where(Machine.is_active.is_(True)).order_by(Machine.name)).all()
    people = db.scalars(select(Personnel).where(Personnel.is_active.is_(True)).order_by(Personnel.full_name)).all()
    losses = db.scalars(select(LossCategory).where(LossCategory.is_active.is_(True)).order_by(LossCategory.name)).all()
    routes = db.execute(
        select(RouteOperation, RouteVersion, Product, Operation)
        .join(RouteVersion, RouteVersion.id == RouteOperation.route_version_id)
        .join(Product, Product.id == RouteVersion.product_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.is_enabled.is_(True), RouteVersion.is_active.is_(True),
               Product.is_active.is_(True), Operation.is_active.is_(True))
    ).all()
    maps = db.scalars(select(OperationMachineMap).where(OperationMachineMap.is_active.is_(True))).all()
    return {"products": products, "machines": machines, "people": people,
            "losses": losses, "routes": routes, "maps": maps}


@router.get("/bulk-template")
def download_oee_bulk_template(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    masters = _oee_workbook_masters(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "OEE Entries"
    headers = ["Entry Ref (Auto)", "Production Date", "Product Name", "Machine Name",
               "Shift", "Operator Name", "Shift Duration Min", "Planned Break Min",
               "Good Qty", "Reject Qty", "Remarks"]
    ws.append(headers)
    for row in range(2, MAX_OEE_BULK_ENTRIES + 2):
        ws.append([row - 1, None, None, None, None, None, 440, 0, None, None, None])
    ws.protection.sheet = True
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = True
    # Entry references and standard defaults are locked; input cells are editable.
    from openpyxl.styles import Protection
    for row in range(2, MAX_OEE_BULK_ENTRIES + 2):
        for col in range(2, 12):
            ws.cell(row, col).protection = Protection(locked=False)
    loss_ws = wb.create_sheet("Loss Details")
    loss_ws.append(["Entry Ref", "Loss Type", "Loss Minutes", "Remarks"])
    for _ in range(MAX_OEE_BULK_LOSS_ROWS):
        loss_ws.append([None, None, None, None])
    master = wb.create_sheet("Master Data")
    master.sheet_state = "hidden"
    master.append(["Product Name", "Machine Name", "Operator Name", "Loss Type", "Shift", "Product ID"])
    # A product/machine pair is offered only when an active effective route and
    # an active machine mapping exist. The importer still checks the selected date.
    pairs = {}
    for route, version, product, operation in masters["routes"]:
        for mapping in masters["maps"]:
            if mapping.route_operation_id == route.id:
                machine = next((m for m in masters["machines"] if m.id == mapping.machine_id), None)
                if machine:
                    pairs.setdefault(product.id, {})[machine.id] = (product, machine)
    for product_id in sorted(pairs, key=lambda pid: next(p.name.casefold() for p in masters["products"] if p.id == pid)):
        product = next(p for p in masters["products"] if p.id == product_id)
        master.append([product.name, None, None, None, None, product.id])
        product_row = master.max_row
        machine_rows = []
        for machine_id, (p, machine) in sorted(pairs[product_id].items(), key=lambda item: item[1][1].name.casefold()):
            master.append([None, machine.name, None, None, None])
            machine_rows.append(master.max_row)
        # Product-specific named range used by the dependent machine dropdown.
        if machine_rows:
            from openpyxl.workbook.defined_name import DefinedName
            range_name = f"ProductMachines_{product_id}"
            wb.defined_names.add(DefinedName(range_name,
                attr_text=f"'Master Data'!$B${machine_rows[0]}:$B${machine_rows[-1]}"))
    # Separate simple lists are stored in columns C-E.
    for i, person in enumerate(masters["people"], start=2):
        master.cell(i, 3, person.full_name)
    for i, loss in enumerate(masters["losses"], start=2):
        master.cell(i, 4, loss.name)
    for i, shift in enumerate(["A", "B", "C"], start=2):
        master.cell(i, 5, shift)
    from openpyxl.workbook.defined_name import DefinedName
    if masters["products"]:
        wb.defined_names.add(DefinedName("ProductNames",
            attr_text=f"'Master Data'!$A$2:$A${master.max_row}"))
    if masters["people"]:
        wb.defined_names.add(DefinedName("Operators", attr_text=f"'Master Data'!$C$2:$C${len(masters['people'])+1}"))
    if masters["losses"]:
        wb.defined_names.add(DefinedName("LossTypes", attr_text=f"'Master Data'!$D$2:$D${len(masters['losses'])+1}"))
    wb.defined_names.add(DefinedName("Shifts", attr_text="'Master Data'!$E$2:$E$4"))
    dv_products = DataValidation(type="list", formula1="=ProductNames", allow_blank=True)
    ws.add_data_validation(dv_products); dv_products.add(f"C2:C{MAX_OEE_BULK_ENTRIES + 1}")
    dv_machines = DataValidation(type="list",
        formula1='=INDIRECT("ProductMachines_"&INDEX(\'Master Data\'!$F$2:$F$2000,MATCH(C2,\'Master Data\'!$A$2:$A$2000,0)))', allow_blank=True)
    ws.add_data_validation(dv_machines); dv_machines.add(f"D2:D{MAX_OEE_BULK_ENTRIES + 1}")
    for formula, target in [("=Shifts", f"E2:E{MAX_OEE_BULK_ENTRIES + 1}"), ("=Operators", f"F2:F{MAX_OEE_BULK_ENTRIES + 1}")]:
        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
        ws.add_data_validation(dv); dv.add(target)
    dv_loss = DataValidation(type="list", formula1="=LossTypes", allow_blank=True)
    loss_ws.add_data_validation(dv_loss); dv_loss.add(f"B2:B{MAX_OEE_BULK_LOSS_ROWS + 1}")
    wb.defined_names.add(DefinedName("EntryRefs", attr_text=f"'OEE Entries'!$A$2:$A${MAX_OEE_BULK_ENTRIES + 1}"))
    dv_refs = DataValidation(type="list", formula1="=EntryRefs", allow_blank=True)
    loss_ws.add_data_validation(dv_refs); dv_refs.add(f"A2:A{MAX_OEE_BULK_LOSS_ROWS + 1}")
    for sheet in (ws, loss_ws):
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="24476B")
            cell.alignment = Alignment(wrap_text=True)
        for col in sheet.columns:
            letter = col[0].column_letter
            sheet.column_dimensions[letter].width = min(max(max(len(str(x.value or "")) for x in col) + 3, 14), 30)
    ws.column_dimensions["A"].width = 18
    output = BytesIO()
    wb.save(output); output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="OEE_Bulk_Upload_Template.xlsx"'})

@router.post("/bulk-import/preview")
async def preview_oee_bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                                  _: User = Depends(get_current_user)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Upload an .xlsx OEE template")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "OEE workbook must be 10 MB or smaller")
    try:
        wb = load_workbook(BytesIO(raw), data_only=True, read_only=True)
        ws = wb["OEE Entries"]; loss_ws = wb["Loss Details"]
    except Exception:
        raise HTTPException(422, "Workbook must contain OEE Entries and Loss Details sheets")
    masters = _oee_workbook_masters(db)
    people = {x.full_name.strip().casefold(): x for x in masters["people"]}
    loss_types = {x.name.strip().casefold(): x for x in masters["losses"]}
    entries = {}
    errors = []
    for row_no, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(v is not None for v in values):
            continue
        ref, prod_date, product_name, machine_name, shift_name, operator_name, shift_min, break_min, good, reject, remarks = (list(values) + [None] * 11)[:11]
        key = str(ref or "").strip()
        if not any(v is not None for v in values[1:]):
            continue
        if not key:
            errors.append({"sheet":"OEE Entries","row":row_no,"error":"Entry Ref is required"}); continue
        try:
            if isinstance(prod_date, datetime): prod_date = prod_date.date()
            elif isinstance(prod_date, str): prod_date = date.fromisoformat(prod_date.strip())
            if not isinstance(prod_date, date): raise ValueError("Production Date is required")
            product_matches = [x for x in masters["products"] if x.name.strip().casefold() == str(product_name or "").strip().casefold()]
            machine_matches = [x for x in masters["machines"] if x.name.strip().casefold() == str(machine_name or "").strip().casefold()]
            if len(product_matches) > 1: raise ValueError("Product Name is duplicated in the active master; ask the administrator to make names unique")
            if len(machine_matches) > 1: raise ValueError("Machine Name is duplicated in the active master; ask the administrator to make names unique")
            product = product_matches[0] if product_matches else None
            machine = machine_matches[0] if machine_matches else None
            person = people.get(str(operator_name or "").strip().casefold())
            if not product: raise ValueError("Product Name is not in the active master")
            if not machine: raise ValueError("Machine Name is not in the active master")
            if not person: raise ValueError("Operator Name is not in active Personnel Master")
            shift_value = str(shift_name or "").strip().upper()
            if shift_value not in {"A","B","C"}: raise ValueError("Shift must be A, B or C")
            route_rows = []
            for candidate in masters["routes"]:
                route, version, route_product, operation = candidate
                if route_product.id != product.id or version.effective_from > prod_date or (version.effective_to and version.effective_to < prod_date):
                    continue
                mapped = any(m.route_operation_id == route.id and m.machine_id == machine.id and m.effective_from <= prod_date and (m.effective_to is None or m.effective_to >= prod_date) for m in masters["maps"])
                if mapped:
                    route_rows.append(route)
            if len(route_rows) != 1:
                raise ValueError("Product + Machine must resolve to exactly one active operation on the production date; check the machine mapping")
            route = route_rows[0]
            ctx = _context(db, product.id, route.id, machine.id, prod_date)
            if machine.id not in ctx["allowed_machine_ids"]:
                raise ValueError("Machine is not explicitly mapped to this product operation on this date")
            if key in entries: raise ValueError("Entry Ref must be unique")
            entries[key] = {"ref":key,"production_date":prod_date,"product_id":product.id,
                "route_operation_id":route.id,"machine_id":machine.id,"operator_id":person.id,
                "shift":shift_value,"shift_duration_min":Decimal(str(shift_min if shift_min is not None else 440)),
                "planned_break_min":Decimal(str(break_min if break_min is not None else 0)),
                "good_count":Decimal(str(good or 0)),"reject_count":Decimal(str(reject or 0)),
                "remarks":str(remarks or ""),"cycle":Decimal(ctx["cycle"].ideal_cycle_time_sec) if ctx["cycle"] else None,
                "losses":[],"row":row_no}
            if entries[key]["shift_duration_min"] <= 0 or entries[key]["planned_break_min"] < 0 or entries[key]["planned_break_min"] >= entries[key]["shift_duration_min"]:
                raise ValueError("Shift duration must be positive and planned break must be smaller")
            if entries[key]["good_count"] < 0 or entries[key]["reject_count"] < 0:
                raise ValueError("Good and reject quantities cannot be negative")
            if not entries[key]["cycle"]: raise ValueError("Effective ideal cycle time is missing in Masters")
            duplicate = db.scalar(select(MachineShiftProduction.id).where(
                MachineShiftProduction.production_date == prod_date, MachineShiftProduction.shift == shift_value,
                MachineShiftProduction.product_id == product.id, MachineShiftProduction.route_operation_id == route.id,
                MachineShiftProduction.machine_id == machine.id).limit(1))
            if duplicate: raise ValueError(f"Duplicate: OEE entry #{duplicate} already exists; bulk import will not overwrite it")
        except Exception as exc:
            errors.append({"sheet":"OEE Entries","row":row_no,"entry_ref":key,"error":str(exc)})
    for row_no, values in enumerate(loss_ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(v is not None for v in values): continue
        ref, loss_name, minutes, remark = (list(values) + [None] * 4)[:4]
        key = str(ref or "").strip()
        try:
            if key not in entries: raise ValueError("Entry Ref does not match an OEE Entries row")
            category = loss_types.get(str(loss_name or "").strip().casefold())
            if not category: raise ValueError("Loss Type is not in active Loss Category Master")
            duration = Decimal(str(minutes))
            if duration <= 0: raise ValueError("Loss Minutes must be greater than zero")
            qty = (duration * Decimal("60") / entries[key]["cycle"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP) if category.oee_component == OEEComponent.AVAILABILITY else Decimal("0")
            if len(entries[key]["losses"]) >= MAX_OEE_BULK_LOSSES_PER_ENTRY:
                raise ValueError(f"Each OEE entry may contain no more than {MAX_OEE_BULK_LOSSES_PER_ENTRY} loss events")
            entries[key]["losses"].append({"loss_category_id":category.id,"duration_min":duration,
                                           "qty_loss":qty,"remark":str(remark or ""),
                                           "component":category.oee_component.value})
        except Exception as exc:
            errors.append({"sheet":"Loss Details","row":row_no,"entry_ref":key,"error":str(exc)})
    entry_limit_error = _oee_bulk_entry_count_error(len(entries))
    if entry_limit_error:
        errors.append({"sheet":"OEE Entries","row":None,"entry_ref":None,"error":entry_limit_error})
    preview = []
    seen_scopes = set()
    for item in entries.values():
        scope = (item["production_date"], item["shift"], item["product_id"], item["route_operation_id"], item["machine_id"])
        if scope in seen_scopes:
            errors.append({"sheet":"OEE Entries","row":item["row"],"entry_ref":item["ref"],
                           "error":"Duplicate machine / product / operation / date / shift entry in this workbook"})
        seen_scopes.add(scope)
        availability = sum((x["duration_min"] for x in item["losses"] if x["component"] == "AVAILABILITY"),Decimal("0"))
        if availability > item["shift_duration_min"] - item["planned_break_min"]:
            errors.append({"sheet":"Loss Details","row":item["row"],"entry_ref":item["ref"],
                           "error":"Total Availability loss minutes exceed planned production time"})
        total_qty = (availability * Decimal("60") / item["cycle"]).quantize(Decimal("1"),rounding=ROUND_HALF_UP)
        preview.append({"entry_ref":item["ref"],"row":item["row"],"date":item["production_date"].isoformat(),
            "shift":item["shift"],"machine_id":item["machine_id"],"product_id":item["product_id"],
            "operator_id":item["operator_id"],"good_qty":float(item["good_count"]),"reject_qty":float(item["reject_count"]),
            "availability_loss_min":float(availability),"calculated_loss_qty":int(total_qty),
            "loss_events":len(item["losses"])})
    wb.close()
    commit_payload = []
    for item in entries.values():
        commit_payload.append({
            "entry": {"production_date":item["production_date"].isoformat(),"shift":item["shift"],
                "product_id":item["product_id"],"route_operation_id":item["route_operation_id"],
                "machine_id":item["machine_id"],"operator_id":item["operator_id"],
                "shift_duration_min":str(item["shift_duration_min"]),"planned_break_min":str(item["planned_break_min"]),
                "good_count":str(item["good_count"]),"reject_count":str(item["reject_count"]),
                "ideal_cycle_time_sec":"0","remarks":item["remarks"]},
            "losses":[{"loss_date":item["production_date"].isoformat(),"shift":item["shift"],
                "product_id":item["product_id"],"route_operation_id":item["route_operation_id"],
                "machine_id":item["machine_id"],"loss_category_id":loss["loss_category_id"],
                "duration_min":str(loss["duration_min"]),"qty_loss":"0","remark":loss["remark"]}
                for loss in item["losses"]]
        })
    return {"valid":not errors,"entry_count":len(preview),"loss_event_count":sum(x["loss_events"] for x in preview),
            "errors":errors,"preview":preview,"commit_payload":commit_payload if not errors else None,
            "message":"Correct all errors before import. Preview does not save records."}


@router.post("/bulk-import/commit")
def commit_oee_bulk_import(payload: dict = Body(...), db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    items = payload.get("entries") if isinstance(payload, dict) else None
    _validate_oee_bulk_commit_entries(items)
    prepared = []
    seen = set()
    try:
        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(422, "Each OEE entry must be an object")
            _validate_oee_bulk_loss_events(item.get("losses"))
            entry_payload = MachineEntryCreate.model_validate(item.get("entry") or {})
            scope = (entry_payload.production_date, entry_payload.shift, entry_payload.product_id,
                     entry_payload.route_operation_id, entry_payload.machine_id)
            if scope in seen:
                raise HTTPException(422, "The workbook contains duplicate machine / product / operation / date / shift entries")
            seen.add(scope)
            duplicate = db.scalar(select(MachineShiftProduction.id).where(
                MachineShiftProduction.production_date == scope[0], MachineShiftProduction.shift == scope[1],
                MachineShiftProduction.product_id == scope[2], MachineShiftProduction.route_operation_id == scope[3],
                MachineShiftProduction.machine_id == scope[4]).limit(1))
            if duplicate:
                raise HTTPException(409, f"Entry already exists as #{duplicate}; import stopped without saving")
            data, context = _prepare_entry(db, entry_payload)
            data["source"] = SourceType.EXCEL
            validated = []
            availability = Decimal("0")
            for loss_raw in item.get("losses") or []:
                loss_payload = LossEventCreate.model_validate(loss_raw)
                if (loss_payload.loss_date != entry_payload.production_date
                    or loss_payload.shift != entry_payload.shift
                    or loss_payload.product_id != entry_payload.product_id
                    or loss_payload.route_operation_id != entry_payload.route_operation_id
                    or loss_payload.machine_id != entry_payload.machine_id):
                    raise HTTPException(422, "Loss event does not match its OEE entry scope")
                loss_data, category = _validate_loss(db, loss_payload)
                loss_data["source"] = SourceType.EXCEL
                loss_data["qty_loss"] = _calculated_loss_qty(loss_payload.duration_min, category, Decimal(data["ideal_cycle_time_sec"]))
                validated.append((loss_data, category))
                if category.oee_component == OEEComponent.AVAILABILITY:
                    availability += loss_payload.duration_min
            _allocate_availability_loss_qty(validated, Decimal(data["ideal_cycle_time_sec"]))
            planned = entry_payload.shift_duration_min - entry_payload.planned_break_min
            if availability > planned:
                raise HTTPException(422, "Availability loss minutes exceed planned time")
            data["downtime_min"] = availability
            prepared.append((data, context, validated))
        imported = []
        for data, context, validated in prepared:
            row = MachineShiftProduction(**data)
            db.add(row); db.flush()
            for loss_data, _category in validated:
                db.add(MachineLossEvent(**loss_data))
            imported.append(row.id)
        db.commit()
        return {"status":"imported","entry_count":len(imported),
                "loss_event_count":sum(len(x[2]) for x in prepared),"entry_ids":imported}
    except HTTPException:
        db.rollback()
        raise
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(422, detail=exc.errors())
    except Exception:
        db.rollback()
        raise


@router.get("/available-machines")
def available_machines(route_operation_id: int, production_date: date,
                       db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    route = db.get(RouteOperation, route_operation_id)
    if not route:
        raise HTTPException(404, "Product operation not found")
    rows = db.execute(
        select(OperationMachineMap, Machine).join(Machine, Machine.id == OperationMachineMap.machine_id).where(
            OperationMachineMap.route_operation_id == route_operation_id,
            OperationMachineMap.is_active.is_(True), Machine.is_active.is_(True),
            OperationMachineMap.effective_from <= production_date,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= production_date),
        ).order_by(OperationMachineMap.priority, Machine.code)
    ).all()
    if rows:
        return {"mapped": True, "machines": [{"id": m.id, "code": m.code, "name": m.name} for _, m in rows]}
    # OEE entry selection must only offer explicitly mapped machines.
    # Returning an empty list lets the mobile client exclude this operation
    # instead of accidentally treating every active machine as a valid mapping.
    return {"mapped": False, "warning": "No active machine mapping exists for this operation on the selected date.",
            "machines": []}


@router.get("/entry-context")
def entry_context(product_id: int, route_operation_id: int, machine_id: int, production_date: date,
                  shift: str = "A", db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    context = _context(db, product_id, route_operation_id, machine_id, production_date)
    existing = db.scalar(select(MachineShiftProduction).where(
        MachineShiftProduction.production_date == production_date,
        MachineShiftProduction.shift == shift.strip().upper(),
        MachineShiftProduction.product_id == product_id,
        MachineShiftProduction.route_operation_id == route_operation_id,
        MachineShiftProduction.machine_id == machine_id,
    ).order_by(MachineShiftProduction.id.desc()).limit(1))
    existing_losses = db.execute(
        select(MachineLossEvent, LossCategory)
        .join(LossCategory, LossCategory.id == MachineLossEvent.loss_category_id)
        .where(
            MachineLossEvent.loss_date == production_date,
            MachineLossEvent.shift == shift.strip().upper(),
            MachineLossEvent.product_id == product_id,
            MachineLossEvent.route_operation_id == route_operation_id,
            MachineLossEvent.machine_id == machine_id,
        ).order_by(MachineLossEvent.id)
    ).all()
    return {
        "product": context["product"].name, "operation": context["operation"].name,
        "machine": context["machine"].code, "allowed_machine_ids": context["allowed_machine_ids"],
        "ideal_cycle_time_sec": float(context["cycle"].ideal_cycle_time_sec) if context["cycle"] else None,
        "warnings": context["warnings"], "existing_entry": _entry_json(existing, context) if existing else None,
        "existing_losses": [{
            "id": event.id, "loss_category_id": event.loss_category_id,
            "category": category.name, "component": category.oee_component.value,
            "duration_min": float(event.duration_min), "qty_loss": float(event.qty_loss),
            "start_time": event.start_time, "end_time": event.end_time,
            "remark": event.remark or "",
        } for event, category in existing_losses],
    }


@router.post("/machine-entry")
def save_machine_entry(payload: MachineEntryCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    duplicate = db.scalar(select(MachineShiftProduction.id).where(
        MachineShiftProduction.production_date == payload.production_date,
        MachineShiftProduction.shift == payload.shift,
        MachineShiftProduction.product_id == payload.product_id,
        MachineShiftProduction.route_operation_id == payload.route_operation_id,
        MachineShiftProduction.machine_id == payload.machine_id,
    ).limit(1))
    if duplicate:
        raise HTTPException(409, f"This machine shift entry already exists as #{duplicate}; load and correct it instead of duplicating it")
    data, context = _prepare_entry(db, payload)
    row = MachineShiftProduction(**data)
    db.add(row); db.commit(); db.refresh(row)
    return {"entry": _entry_json(row, context), "warnings": context["warnings"]}



@router.post("/machine-entry-with-losses")
def save_machine_entry_with_losses(
    payload: OEEEntryWithLossesCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Atomically save/correct a production entry and append its classified loss events."""
    entry_payload = payload.entry
    row = db.get(MachineShiftProduction, payload.entry_id) if payload.entry_id else None
    if payload.entry_id and not row:
        raise HTTPException(404, "Machine shift entry not found")

    if row:
        reason = (payload.correction_reason or "").strip()
        if len(reason) < 5:
            raise HTTPException(422, "Enter a correction reason of at least 5 characters")
        scope = (row.production_date, row.shift, row.product_id, row.route_operation_id, row.machine_id)
        requested_scope = (entry_payload.production_date, entry_payload.shift, entry_payload.product_id,
                           entry_payload.route_operation_id, entry_payload.machine_id)
        if scope != requested_scope:
            raise HTTPException(422, "An existing entry's date, shift, product, operation and machine cannot be changed")
        before = {key: str(getattr(row, key)) if getattr(row, key) is not None else None
                  for key in ("production_date", "shift", "product_id", "route_operation_id", "machine_id",
                              "shift_duration_min", "planned_break_min", "downtime_min", "total_count",
                              "good_count", "reject_count", "ideal_cycle_time_sec", "operator_id", "remarks")}
    else:
        duplicate = db.scalar(select(MachineShiftProduction.id).where(
            MachineShiftProduction.production_date == entry_payload.production_date,
            MachineShiftProduction.shift == entry_payload.shift,
            MachineShiftProduction.product_id == entry_payload.product_id,
            MachineShiftProduction.route_operation_id == entry_payload.route_operation_id,
            MachineShiftProduction.machine_id == entry_payload.machine_id,
        ).limit(1))
        if duplicate:
            raise HTTPException(409, f"This machine shift entry already exists as #{duplicate}; load and correct it instead of duplicating it")
        before = None

    data, context = _prepare_entry(db, entry_payload)
    validated_losses: list[tuple[dict, LossCategory]] = []
    availability_downtime = Decimal("0")
    if row:
        previous_losses = db.execute(
            select(MachineLossEvent, LossCategory)
            .join(LossCategory, LossCategory.id == MachineLossEvent.loss_category_id)
            .where(
                MachineLossEvent.loss_date == entry_payload.production_date,
                MachineLossEvent.shift == entry_payload.shift,
                MachineLossEvent.product_id == entry_payload.product_id,
                MachineLossEvent.route_operation_id == entry_payload.route_operation_id,
                MachineLossEvent.machine_id == entry_payload.machine_id,
            )
        ).all()
        availability_downtime += sum(
            (event.duration_min for event, category in previous_losses
             if category.oee_component == OEEComponent.AVAILABILITY),
            Decimal("0"),
        )
    effective_cycle = Decimal(data["ideal_cycle_time_sec"])
    for loss_payload in payload.losses:
        loss_data, category = _validate_loss(db, loss_payload)
        # Loss quantity is system-calculated from availability minutes and the
        # effective master cycle. Users do not supply or override this value.
        loss_data["qty_loss"] = _calculated_loss_qty(
            loss_payload.duration_min, category, effective_cycle
        )
        validated_losses.append((loss_data, category))
        if category.oee_component == OEEComponent.AVAILABILITY:
            availability_downtime += loss_payload.duration_min

    _allocate_availability_loss_qty(validated_losses, effective_cycle)
    planned_minutes = entry_payload.shift_duration_min - entry_payload.planned_break_min
    if availability_downtime > planned_minutes:
        raise HTTPException(422, "Availability loss minutes cannot exceed planned production time")
    data["downtime_min"] = availability_downtime

    try:
        if row:
            for key, value in data.items():
                setattr(row, key, value)
        else:
            row = MachineShiftProduction(**data)
            db.add(row)
        db.flush()
        if before is not None:
            after = {key: str(getattr(row, key)) if getattr(row, key) is not None else None for key in before}
            db.add(GovernanceAudit(
                actor_id=user.id, event="OEE_ENTRY_CORRECTED", entity="machine_shift_production",
                entity_id=str(row.id), month=row.production_date.replace(day=1), reason=payload.correction_reason.strip(),
                before_json=json.dumps(before, default=str), after_json=json.dumps(after, default=str),
            ))
        saved_losses = []
        for loss_data, category in validated_losses:
            event = MachineLossEvent(**loss_data)
            db.add(event)
            db.flush()
            saved_losses.append({
                "id": event.id, "category": category.name,
                "component": category.oee_component.value,
                "duration_min": float(event.duration_min),
            })
        db.commit()
        db.refresh(row)
        return {
            "entry": _entry_json(row, context),
            "losses": saved_losses,
            "warnings": context["warnings"],
            "total_count": float(row.total_count),
            "downtime_min": float(row.downtime_min),
        }
    except Exception:
        db.rollback()
        raise


@router.put("/machine-entry/{entry_id}")
def update_machine_entry(entry_id: int, payload: MachineEntryCreate, request: Request,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(MachineShiftProduction, entry_id)
    if not row:
        raise HTTPException(404, "Machine shift entry not found")
    reason = (request.headers.get("X-Change-Reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "Enter a correction reason of at least 5 characters before updating an OEE entry")
    before = {key: str(getattr(row, key)) if getattr(row, key) is not None else None
              for key in ("production_date", "shift", "product_id", "route_operation_id", "machine_id",
                          "shift_duration_min", "planned_break_min", "downtime_min", "total_count",
                          "good_count", "reject_count", "ideal_cycle_time_sec", "remarks")}
    duplicate = db.scalar(select(MachineShiftProduction.id).where(
        MachineShiftProduction.production_date == payload.production_date,
        MachineShiftProduction.shift == payload.shift,
        MachineShiftProduction.product_id == payload.product_id,
        MachineShiftProduction.route_operation_id == payload.route_operation_id,
        MachineShiftProduction.machine_id == payload.machine_id,
        MachineShiftProduction.id != entry_id,
    ).limit(1))
    if duplicate:
        raise HTTPException(409, f"Another matching machine shift entry already exists as #{duplicate}")
    data, context = _prepare_entry(db, payload)
    for key, value in data.items():
        setattr(row, key, value)
    after = {key: str(getattr(row, key)) if getattr(row, key) is not None else None for key in before}
    db.add(GovernanceAudit(actor_id=user.id, event="OEE_ENTRY_CORRECTED", entity="machine_shift_production",
                           entity_id=str(row.id), month=row.production_date.replace(day=1), reason=reason,
                           before_json=json.dumps(before, default=str), after_json=json.dumps(after, default=str)))
    db.commit(); db.refresh(row)
    return {"entry": _entry_json(row, context), "warnings": context["warnings"]}


def _calculated_loss_qty(duration_min: Decimal, category: LossCategory, cycle_time_sec: Decimal | None) -> Decimal:
    """Return whole-piece loss quantity for availability losses only."""
    if category.oee_component != OEEComponent.AVAILABILITY or not cycle_time_sec or cycle_time_sec <= 0:
        return Decimal("0")
    return ((Decimal(duration_min) * Decimal("60")) / Decimal(cycle_time_sec)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )


def _allocate_availability_loss_qty(losses: list[tuple[dict, LossCategory]], cycle_time_sec: Decimal) -> None:
    """Allocate the rounded total piece loss across availability events.

    This ensures the sum of event quantities equals the quantity calculated
    from total availability minutes, rather than rounding each event upward.
    """
    eligible = [(data, category) for data, category in losses
                if category.oee_component == OEEComponent.AVAILABILITY]
    if not eligible or cycle_time_sec <= 0:
        return
    exact = [(data, Decimal(data["duration_min"]) * Decimal("60") / cycle_time_sec)
             for data, _ in eligible]
    total_qty = sum((qty for _, qty in exact), Decimal("0")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    allocated = [int(qty) for _, qty in exact]
    remaining = int(total_qty) - sum(allocated)
    order = sorted(range(len(exact)), key=lambda i: exact[i][1] - allocated[i], reverse=True)
    for i in order[:max(0, remaining)]:
        allocated[i] += 1
    for (data, _), qty in zip(eligible, allocated):
        data["qty_loss"] = Decimal(qty)


def _validate_loss(db: Session, payload: LossEventCreate) -> tuple[dict, LossCategory]:
    if payload.product_id is not None and payload.route_operation_id is not None:
        _context(db, payload.product_id, payload.route_operation_id, payload.machine_id, payload.loss_date)
    elif not db.get(Machine, payload.machine_id):
        raise HTTPException(404, "Machine not found")
    category = db.get(LossCategory, payload.loss_category_id)
    if not category or not category.is_active:
        raise HTTPException(422, "Select an active loss category")
    return payload.model_dump(), category


@router.post("/loss-events")
def save_loss(payload: LossEventCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data, category = _validate_loss(db, payload)
    row = MachineLossEvent(**data)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "category": category.name, "component": category.oee_component.value}


@router.put("/loss-events/{loss_id}")
def update_loss(loss_id: int, payload: LossEventCreate, request: Request,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(MachineLossEvent, loss_id)
    if not row:
        raise HTTPException(404, "Loss event not found")
    reason = (request.headers.get("X-Change-Reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "Enter a correction reason of at least 5 characters before updating a loss event")
    before = {key: str(getattr(row, key)) if getattr(row, key) is not None else None
              for key in ("loss_date", "shift", "product_id", "route_operation_id", "machine_id",
                          "loss_category_id", "start_time", "end_time", "duration_min", "qty_loss", "remark")}
    data, category = _validate_loss(db, payload)
    effective_cycle = None
    if payload.product_id is not None and payload.route_operation_id is not None:
        context = _context(db, payload.product_id, payload.route_operation_id, payload.machine_id, payload.loss_date)
        effective_cycle = Decimal(context["cycle"].ideal_cycle_time_sec) if context["cycle"] else None
    data["qty_loss"] = _calculated_loss_qty(payload.duration_min, category, effective_cycle)
    for key, value in data.items():
        setattr(row, key, value)
    after = {key: str(getattr(row, key)) if getattr(row, key) is not None else None for key in before}
    db.add(GovernanceAudit(actor_id=user.id, event="OEE_LOSS_CORRECTED", entity="machine_loss_events",
                           entity_id=str(row.id), month=row.loss_date.replace(day=1), reason=reason,
                           before_json=json.dumps(before, default=str), after_json=json.dumps(after, default=str)))
    db.commit(); db.refresh(row)
    return {"id": row.id, "category": category.name, "component": category.oee_component.value}


def _summary(db: Session, machine_id: int, summary_date: date, shift: str | None,
             product_id: int | None, route_operation_id: int | None) -> dict:
    q = select(MachineShiftProduction).where(
        MachineShiftProduction.machine_id == machine_id,
        MachineShiftProduction.production_date == summary_date,
    )
    loss_q = select(MachineLossEvent).where(
        MachineLossEvent.machine_id == machine_id,
        MachineLossEvent.loss_date == summary_date,
    )
    if shift:
        q = q.where(MachineShiftProduction.shift == shift)
        loss_q = loss_q.where(MachineLossEvent.shift == shift)
    if product_id is not None:
        q = q.where(MachineShiftProduction.product_id == product_id)
        loss_q = loss_q.where(MachineLossEvent.product_id == product_id)
    if route_operation_id is not None:
        q = q.where(MachineShiftProduction.route_operation_id == route_operation_id)
        loss_q = loss_q.where(MachineLossEvent.route_operation_id == route_operation_id)
    rows = db.scalars(q.order_by(MachineShiftProduction.id)).all()
    losses = db.scalars(loss_q.order_by(MachineLossEvent.id)).all()

    categories = {x.id: x for x in db.scalars(select(LossCategory)).all()}
    action_rows = db.execute(
        select(ActionContext.loss_event_id, Action).join(Action, Action.id == ActionContext.action_id)
        .where(ActionContext.loss_event_id.in_([x.id for x in losses] or [-1]))
        .order_by(Action.id.desc())
    ).all()
    loss_actions: dict[int, Action] = {}
    for loss_event_id, action in action_rows:
        loss_actions.setdefault(loss_event_id, action)

    summary = None
    if rows:
        summary = aggregate_oee_entries(rows)
        availability_loss = sum(float(x.duration_min) for x in losses
                                if categories.get(x.loss_category_id) and categories[x.loss_category_id].oee_component == OEEComponent.AVAILABILITY)
        # Derive reconciliation values from the same deduplicated machine-shift aggregate.
        # Product quantities remain additive across rows in the selected scope.
        downtime = max(0.0, summary["planned_production_min"] - summary["run_time_min"])
        total_count = sum(float(row.total_count or 0) for row in rows)
        good_count = sum(float(row.good_count or 0) for row in rows)
        summary["captured_loss_min"] = availability_loss
        summary["unclassified_loss_min"] = max(0.0, downtime - availability_loss)
        summary["overclassified_loss_min"] = max(0.0, availability_loss - downtime)
        summary["reject_or_unaccounted_count"] = max(0.0, total_count - good_count)

    entry_data = []
    for row in rows:
        try:
            ctx = _context(db, row.product_id, row.route_operation_id, row.machine_id, row.production_date)
        except HTTPException:
            ctx = None
        entry_data.append(_entry_json(row, ctx))
    loss_data = []
    for row in losses:
        category = categories.get(row.loss_category_id)
        action = loss_actions.get(row.id)
        loss_data.append({
            "id": row.id, "loss_category_id": row.loss_category_id,
            "category": category.name if category else f"Loss #{row.loss_category_id}",
            "component": category.oee_component.value if category else None,
            "duration_min": float(row.duration_min), "qty_loss": float(row.qty_loss),
            "start_time": row.start_time, "end_time": row.end_time, "remark": row.remark,
            "action_id": action.id if action else None, "action_no": action.action_no if action else None,
            "action_status": action.status.value if action else None,
        })
    return {
        "machine_id": machine_id, "date": summary_date, "shift": shift,
        "product_id": product_id, "route_operation_id": route_operation_id,
        "entries": entry_data, "summary": summary, "losses": loss_data,
    }


@router.get("/recent-records")
def recent_records(from_date: date, to_date: date, product_id: int, route_operation_id: int,
                   shift: str | None = None, machine_id: int | None = None,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Return recent OEE entries for a part/operation, optionally narrowed to one shift and machine."""
    normalized_shift = shift.strip().upper() if shift and shift.strip() else None
    if normalized_shift == "ALL":
        normalized_shift = None
    if normalized_shift is not None and normalized_shift not in {"A", "B", "C"}:
        raise HTTPException(422, "shift must be A, B, C or ALL")
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    query = select(MachineShiftProduction).where(
        MachineShiftProduction.production_date >= from_date,
        MachineShiftProduction.production_date <= to_date,
        MachineShiftProduction.product_id == product_id,
        MachineShiftProduction.route_operation_id == route_operation_id,
    )
    if normalized_shift is not None:
        query = query.where(MachineShiftProduction.shift == normalized_shift)
    if machine_id is not None:
        query = query.where(MachineShiftProduction.machine_id == machine_id)
    rows = db.scalars(
        query.order_by(MachineShiftProduction.production_date.desc(),
                       MachineShiftProduction.shift.asc(), MachineShiftProduction.id.desc())
    ).all()
    records = []
    for row in rows:
        try:
            context = _context(db, row.product_id, row.route_operation_id, row.machine_id, row.production_date)
        except HTTPException:
            context = None
        records.append(_entry_json(row, context))
    return {"from_date": from_date, "to_date": to_date, "shift": normalized_shift or "ALL",
            "machine_id": machine_id, "product_id": product_id, "route_operation_id": route_operation_id,
            "count": len(records), "records": records}
@router.get("/reporting-compliance")
def reporting_compliance(from_date: date, to_date: date, product_id: int | None = None,
                         route_operation_id: int | None = None, machine_id: int | None = None,
                         plant: str | None = None, db: Session = Depends(get_db),
                         _: User = Depends(get_current_user)):
    """Compare planned machine/product/operation/shift slots with submitted OEE entries.

    Expected slots are derived only from positive daily production requirements,
    the latest effective monthly machine allocation, effective machine mapping,
    effective machine shift capacity and the plant working calendar.
    """
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    if (to_date - from_date).days > 92:
        raise HTTPException(422, "Reporting compliance period cannot exceed 93 days")

    expected = []
    configuration_issues = []
    entries = db.scalars(select(MachineShiftProduction).where(
        MachineShiftProduction.production_date >= from_date,
        MachineShiftProduction.production_date <= to_date,
    )).all()
    entry_by_key = {
        (x.production_date, x.shift.upper(), x.product_id, x.route_operation_id, x.machine_id): x
        for x in entries
    }

    machines = {x.id: x for x in db.scalars(select(Machine).where(Machine.is_active.is_(True))).all()}
    products = {x.id: x for x in db.scalars(select(Product)).all()}
    calendar_rows = db.scalars(select(WorkingCalendar).where(
        WorkingCalendar.work_date >= from_date, WorkingCalendar.work_date <= to_date
    )).all()
    calendar_by_key = {(x.work_date, x.plant): x for x in calendar_rows}

    day = from_date
    while day <= to_date:
        month_start = day.replace(day=1)
        month_allocations = db.scalars(select(MachineMonthlyAllocation).where(
            MachineMonthlyAllocation.month == month_start,
            MachineMonthlyAllocation.effective_from <= day,
        )).all()

        # Keep the latest effective allocation revision for each product,
        # operation and machine as of the reporting date.
        latest_allocations = {}
        for allocation in month_allocations:
            key = (allocation.product_id, allocation.route_operation_id, allocation.machine_id)
            previous = latest_allocations.get(key)
            if previous is None or (allocation.effective_from, allocation.revision_no, allocation.id) > (
                previous.effective_from, previous.revision_no, previous.id
            ):
                latest_allocations[key] = allocation

        requirements = db.scalars(select(DailyRequirement).where(
            DailyRequirement.req_date == day
        )).all()
        planned_requirements = [
            r for r in requirements
            if float(r.revised_plan_qty if r.revised_plan_qty is not None else r.baseline_plan_qty or 0) > 0
            and (product_id is None or r.product_id == product_id)
            and (route_operation_id is None or r.route_operation_id in (None, route_operation_id))
        ]

        # Effective machine-to-operation mappings only; no implicit fallback.
        mappings = db.scalars(select(OperationMachineMap).where(
            OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= day,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= day),
        )).all()
        mapped_pairs = {(m.route_operation_id, m.machine_id) for m in mappings}

        capacity_rows = db.scalars(select(MachineCapacitySetting).where(
            MachineCapacitySetting.effective_from <= day,
            or_(MachineCapacitySetting.effective_to.is_(None), MachineCapacitySetting.effective_to >= day),
        )).all()
        capacity_by_machine = {}
        for setting in capacity_rows:
            previous = capacity_by_machine.get(setting.machine_id)
            if previous is None or (setting.effective_from, setting.id) > (previous.effective_from, previous.id):
                capacity_by_machine[setting.machine_id] = setting

        day_expected = []
        for requirement in planned_requirements:
            req_qty = float(requirement.revised_plan_qty if requirement.revised_plan_qty is not None else requirement.baseline_plan_qty or 0)
            candidates = [
                allocation for allocation in latest_allocations.values()
                if allocation.product_id == requirement.product_id
                and (requirement.route_operation_id is None or allocation.route_operation_id == requirement.route_operation_id)
                and float(allocation.allocated_qty or 0) > 0
            ]
            for allocation in candidates:
                machine = machines.get(allocation.machine_id)
                if not machine or (machine_id is not None and machine.id != machine_id):
                    continue
                if plant and (machine.plant or "") != plant:
                    continue
                if (allocation.route_operation_id, machine.id) not in mapped_pairs:
                    configuration_issues.append({
                        "date": day, "product_id": allocation.product_id,
                        "route_operation_id": allocation.route_operation_id,
                        "machine_id": machine.id, "machine": machine.code,
                        "issue": "Missing effective machine-process mapping",
                    })
                    continue
                plant_name = machine.plant or "Main Plant"
                calendar = calendar_by_key.get((day, plant_name))
                if calendar and not calendar.is_working_day:
                    continue
                capacity = capacity_by_machine.get(machine.id)
                if not capacity or capacity.shifts_per_day <= 0:
                    configuration_issues.append({
                        "date": day, "product_id": allocation.product_id,
                        "route_operation_id": allocation.route_operation_id,
                        "machine_id": machine.id, "machine": machine.code,
                        "issue": "Missing effective machine shift-capacity setting",
                    })
                    continue
                shift_names = ["A", "B", "C"][:min(int(capacity.shifts_per_day), 3)]
                for shift_name in shift_names:
                    key = (day, shift_name, allocation.product_id, allocation.route_operation_id, machine.id)
                    row = entry_by_key.get(key)
                    item = {
                        "date": day, "shift": shift_name,
                        "product_id": allocation.product_id,
                        "product": products[allocation.product_id].name if allocation.product_id in products else str(allocation.product_id),
                        "route_operation_id": allocation.route_operation_id,
                        "machine_id": machine.id, "machine": machine.code,
                        "machine_name": machine.name, "plant": plant_name,
                        "planned_qty": req_qty, "status": "PENDING",
                        "entry_id": None, "operator_id": None, "issues": [],
                    }
                    if row:
                        item["entry_id"] = row.id
                        item["operator_id"] = row.operator_id
                        issues = []
                        if row.operator_id is None:
                            issues.append("Operator not selected")
                        if float(row.shift_duration_min or 0) <= 0:
                            issues.append("Shift duration missing")
                        if float(row.ideal_cycle_time_sec or 0) <= 0:
                            issues.append("Ideal cycle time missing")
                        counts = [float(row.total_count or 0), float(row.good_count or 0), float(row.reject_count or 0)]
                        if any(value < 0 for value in counts):
                            issues.append("Negative production quantity")
                        if abs(counts[0] - counts[1] - counts[2]) > 0.001:
                            issues.append("Total quantity is not equal to good plus rejection")
                        item["issues"] = issues
                        item["status"] = "INCOMPLETE" if issues else "UPDATED"
                    day_expected.append(item)
        expected.extend(day_expected)
        day = date.fromordinal(day.toordinal() + 1)

    counts = {
        "expected": len(expected),
        "updated": sum(1 for x in expected if x["status"] == "UPDATED"),
        "pending": sum(1 for x in expected if x["status"] == "PENDING"),
        "incomplete": sum(1 for x in expected if x["status"] == "INCOMPLETE"),
    }
    by_shift = []
    for shift_name in ("A", "B", "C"):
        rows = [x for x in expected if x["shift"] == shift_name]
        if rows:
            by_shift.append({
                "shift": shift_name, "expected": len(rows),
                "updated": sum(1 for x in rows if x["status"] == "UPDATED"),
                "pending": sum(1 for x in rows if x["status"] == "PENDING"),
                "incomplete": sum(1 for x in rows if x["status"] == "INCOMPLETE"),
            })
    counts["compliance_percent"] = round((counts["updated"] / counts["expected"]) * 100, 1) if counts["expected"] else 100.0
    return {
        "from_date": from_date, "to_date": to_date, "plant": plant,
        **counts, "by_shift": by_shift,
        "pending_entries": [x for x in expected if x["status"] == "PENDING"],
        "incomplete_entries": [x for x in expected if x["status"] == "INCOMPLETE"],
        "configuration_issues": configuration_issues,
        "expected_entries": expected,
    }


@router.get("/management-summary")
def management_summary(from_date: date, to_date: date, machine_id: int | None = None,
                       route_operation_id: int | None = None, product_id: str | None = None, plant: str | None = None,
                       product_group: str | None = None, customer_id: str | None = None,
                       target_oee: float = 0.85, recurring_event_threshold: int = 3,
                       db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    q = select(MachineShiftProduction).where(
        MachineShiftProduction.production_date >= from_date,
        MachineShiftProduction.production_date <= to_date,
    )
    lq = select(MachineLossEvent).where(
        MachineLossEvent.loss_date >= from_date, MachineLossEvent.loss_date <= to_date,
    )
    if machine_id is not None:
        q = q.where(MachineShiftProduction.machine_id == machine_id)
        lq = lq.where(MachineLossEvent.machine_id == machine_id)
    if route_operation_id is not None:
        q = q.where(MachineShiftProduction.route_operation_id == route_operation_id)
        lq = lq.where(MachineLossEvent.route_operation_id == route_operation_id)
    plants = csv_strings(plant)
    product_ids = csv_ints(product_id)
    groups = csv_strings(product_group)
    customer_ids = csv_ints(customer_id)
    if plants:
        q = q.join(Machine, Machine.id == MachineShiftProduction.machine_id).where(Machine.plant.in_(plants))
        lq = lq.join(Machine, Machine.id == MachineLossEvent.machine_id).where(Machine.plant.in_(plants))
    if product_ids or groups or customer_ids:
        q = q.join(Product, Product.id == MachineShiftProduction.product_id)
        lq = lq.join(Product, Product.id == MachineLossEvent.product_id)
        if product_ids:
            q = q.where(Product.id.in_(product_ids))
            lq = lq.where(Product.id.in_(product_ids))
        if groups:
            q = q.where(Product.product_group.in_(groups))
            lq = lq.where(Product.product_group.in_(groups))
        if customer_ids:
            q = q.where(Product.customer_id.in_(customer_ids))
            lq = lq.where(Product.customer_id.in_(customer_ids))
    rows = db.scalars(q.order_by(MachineShiftProduction.production_date, MachineShiftProduction.id)).all()
    losses = db.scalars(lq.order_by(MachineLossEvent.loss_date, MachineLossEvent.id)).all()
    machines = {x.id: x for x in db.scalars(select(Machine)).all()}
    categories = {x.id: x for x in db.scalars(select(LossCategory)).all()}

    def aggregate(items):
        return aggregate_oee_entries(items)

    by_day = {}
    by_machine = {}
    for row in rows:
        by_day.setdefault(row.production_date, []).append(row)
        by_machine.setdefault(row.machine_id, []).append(row)
    trend = [{"date": day, **aggregate(items)} for day, items in sorted(by_day.items())]
    machine_summary = []
    for mid, items in by_machine.items():
        metric = aggregate(items)
        status = "ON TARGET" if metric["oee_reported"] >= target_oee else "BELOW TARGET"
        machine_summary.append({"machine_id": mid, "machine": machines[mid].code if mid in machines else str(mid),
                                "machine_name": machines[mid].name if mid in machines else str(mid),
                                "entry_count": len(items), "status": status,
                                "gap_to_target": max(0.0, target_oee - metric["oee_reported"]), **metric})
    machine_summary.sort(key=lambda x: x["oee_reported"])

    # Additional report dimensions use the same shared-machine-time-safe
    # aggregator as the overall and machine summaries.
    by_product = {}
    by_operator = {}
    by_shift = {}
    for row in rows:
        by_product.setdefault(row.product_id, []).append(row)
        by_operator.setdefault(row.operator_id, []).append(row)
        by_shift.setdefault(row.shift, []).append(row)
    product_rows = {x.id: x for x in db.scalars(select(Product)).all()}
    personnel_rows = {x.id: x for x in db.scalars(select(Personnel)).all()}
    product_summary = [
        {"product_id": pid, "product": product_rows[pid].name if pid in product_rows else str(pid),
         "entry_count": len(items), **aggregate(items)}
        for pid, items in by_product.items()
    ]
    product_summary.sort(key=lambda x: x["oee_reported"])
    operator_summary = [
        {"operator_id": oid, "operator": personnel_rows[oid].full_name if oid in personnel_rows else "Unassigned",
         "entry_count": len(items), **aggregate(items)}
        for oid, items in by_operator.items()
    ]
    operator_summary.sort(key=lambda x: x["oee_reported"])
    shift_summary = [
        {"shift": shift_name, "entry_count": len(items), **aggregate(items)}
        for shift_name, items in by_shift.items()
    ]
    shift_summary.sort(key=lambda x: x["shift"])

    pareto = {}
    for loss in losses:
        category = categories.get(loss.loss_category_id)
        name = category.name if category else f"Loss #{loss.loss_category_id}"
        item = pareto.setdefault(name, {"category": name, "component": category.oee_component.value if category else None,
                                       "minutes": 0.0, "qty_loss": 0.0, "events": 0})
        item["minutes"] += float(loss.duration_min)
        item["qty_loss"] += float(loss.qty_loss)
        item["events"] += 1
    loss_pareto = sorted(pareto.values(), key=lambda x: (x["minutes"], x["events"]), reverse=True)
    recurring_losses = [x for x in loss_pareto if x["events"] >= recurring_event_threshold]
    overall = aggregate(rows)
    below_target = [x for x in machine_summary if x["status"] == "BELOW TARGET"]
    return {"from_date": from_date, "to_date": to_date, "target_oee": target_oee,
            "entry_count": len(rows), "loss_event_count": len(losses),
            "below_target_machine_count": len(below_target), "recurring_loss_count": len(recurring_losses),
            "overall": overall, "trend": trend, "machines": machine_summary,
            "products": product_summary, "operators": operator_summary, "shifts": shift_summary,
            "loss_pareto": loss_pareto, "recurring_losses": recurring_losses}


@router.get("/machine-summary")
def machine_summary(machine_id: int, summary_date: date, shift: str | None = None,
                    product_id: int | None = None, route_operation_id: int | None = None,
                    db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _summary(db, machine_id, summary_date, shift, product_id, route_operation_id)


def _add_review_link(db: Session, action: Action) -> None:
    active = db.scalar(select(ReviewSession).where(
        ReviewSession.review_date == action.reference_date, ReviewSession.ended_at.is_(None),
    ).order_by(ReviewSession.id.desc()).limit(1))
    if active:
        db.add(ReviewActionLink(review_session_id=active.id, action_id=action.id))


def _new_action(db: Session, user: User, *, reference_date: date, product_id: int | None,
                route_operation_id: int | None, machine_id: int, loss_event_id: int | None,
                payload: OEEActionCreate, problem_category: str, problem_description: str,
                kpi_type: str, kpi_value: Decimal, gap: Decimal) -> Action:
    action = Action(
        action_no=f"ACT-{reference_date.year}-{db.query(Action).count() + 1:05d}",
        reference_date=reference_date, problem_category=problem_category,
        problem_description=problem_description, action_description=payload.action_description,
        owner_id=payload.owner_id, due_at=payload.due_at, priority=payload.priority,
        kpi_type=kpi_type, kpi_value_when_raised=kpi_value, gap_when_raised=gap,
    )
    db.add(action); db.flush()
    db.add(ActionContext(action_id=action.id, context_date=reference_date, product_id=product_id,
                         route_operation_id=route_operation_id, machine_id=machine_id,
                         loss_event_id=loss_event_id))
    db.add(ActionWhyWhy(action_id=action.id, containment_action=payload.action_description, updated_by_id=user.id))
    db.add(ActionHistory(action_id=action.id, changed_by_id=user.id, new_status=action.status,
                         comment="Action raised from Machine / OEE; standard Why-Why plan opened"))
    _add_review_link(db, action)
    db.commit(); db.refresh(action)
    return action


@router.post("/loss-events/{loss_id}/raise-action")
def raise_loss_action(loss_id: int, payload: OEEActionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loss = db.get(MachineLossEvent, loss_id)
    if not loss:
        raise HTTPException(404, "Loss event not found")
    existing = db.execute(
        select(Action).join(ActionContext, ActionContext.action_id == Action.id)
        .where(ActionContext.loss_event_id == loss_id).order_by(Action.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        return {"status": "already_linked", "action_id": existing.id, "action_no": existing.action_no}
    category = db.get(LossCategory, loss.loss_category_id)
    machine = db.get(Machine, loss.machine_id)
    description = f"{category.name if category else 'Machine loss'} on {machine.code if machine else 'machine'}: {float(loss.duration_min):g} min"
    if loss.remark:
        description += f" — {loss.remark}"
    action = _new_action(
        db, user, reference_date=loss.loss_date, product_id=loss.product_id,
        route_operation_id=loss.route_operation_id, machine_id=loss.machine_id,
        loss_event_id=loss.id, payload=payload, problem_category="OEE / Machine Loss",
        problem_description=description, kpi_type="OEE_LOSS_MIN",
        kpi_value=Decimal(loss.duration_min), gap=Decimal(loss.duration_min),
    )
    return {"status": "created", "action_id": action.id, "action_no": action.action_no}


@router.post("/raise-action")
def raise_oee_action(payload: OEESummaryActionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    summary_data = _summary(db, payload.machine_id, payload.production_date, payload.shift.strip().upper(),
                            payload.product_id, payload.route_operation_id)
    summary = summary_data["summary"]
    if not summary:
        raise HTTPException(422, "Save the machine shift entry before raising an OEE action")
    existing = db.execute(
        select(Action).join(ActionContext, ActionContext.action_id == Action.id).where(
            Action.reference_date == payload.production_date, Action.kpi_type == "OEE",
            Action.status != ActionStatus.CLOSED, ActionContext.machine_id == payload.machine_id,
            ActionContext.product_id == payload.product_id,
            ActionContext.route_operation_id == payload.route_operation_id,
            ActionContext.loss_event_id.is_(None),
        ).order_by(Action.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        return {"status": "already_linked", "action_id": existing.id, "action_no": existing.action_no}
    machine = db.get(Machine, payload.machine_id)
    oee_value = Decimal(str(summary["oee_reported"]))
    gap = max(Decimal("0"), payload.target_oee - oee_value)
    description = (
        f"{machine.code if machine else 'Machine'} shift {payload.shift.upper()} OEE "
        f"{float(oee_value) * 100:.1f}% against {float(payload.target_oee) * 100:.1f}% target"
    )
    if summary.get("unclassified_loss_min", 0) > 0:
        description += f"; {summary['unclassified_loss_min']:.1f} downtime minutes are not classified"
    action = _new_action(
        db, user, reference_date=payload.production_date, product_id=payload.product_id,
        route_operation_id=payload.route_operation_id, machine_id=payload.machine_id,
        loss_event_id=None, payload=payload, problem_category="OEE / Low OEE",
        problem_description=description, kpi_type="OEE", kpi_value=oee_value, gap=gap,
    )
    return {"status": "created", "action_id": action.id, "action_no": action.action_no}
