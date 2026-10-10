from datetime import date, datetime
from io import BytesIO
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import ActionStatus, Priority
from ..models import Action, ActionHistory, ActionWhyWhy, ReviewActionLink, ReviewPoint, ReviewSession, User
from ..schemas import ReviewClose, ReviewStart

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewPointCreate(BaseModel):
    category: str | None = Field(default=None, max_length=120)
    discussion_point: str = Field(min_length=2)
    action_required: bool = False
    action_description: str | None = None
    owner_id: int | None = None
    due_at: datetime | None = None
    priority: Priority = Priority.MEDIUM


def serialize_review(row: ReviewSession, db: Session | None = None) -> dict:
    result = {"id": row.id, "review_date": row.review_date, "started_at": row.started_at,
              "ended_at": row.ended_at, "participants": row.participants,
              "total_sales_gap": float(row.total_sales_gap) if row.total_sales_gap is not None else None,
              "comments": row.comments}
    if db is not None:
        action_ids = select(ReviewPoint.action_id).where(
            ReviewPoint.review_session_id == row.id,
            ReviewPoint.action_id.is_not(None),
        )
        result["action_count"] = db.scalar(select(func.count(Action.id)).where(Action.id.in_(action_ids))) or 0
        result["closed_action_count"] = db.scalar(select(func.count(Action.id)).where(
            Action.id.in_(action_ids), Action.status == ActionStatus.CLOSED
        )) or 0
    return result


def action_data(db: Session, a: Action | None) -> dict | None:
    if not a:
        return None
    owner = db.get(User, a.owner_id) if a.owner_id else None
    return {"id": a.id, "action_no": a.action_no, "description": a.action_description,
            "owner_id": a.owner_id, "owner": owner.full_name if owner else None,
            "due_at": a.due_at, "priority": a.priority.value, "status": a.status.value,
            "age_days": max(0, (date.today() - a.reference_date).days),
            "overdue_days": max(0, (date.today() - a.due_at.date()).days) if a.due_at and a.status != ActionStatus.CLOSED else 0,
            "requires_whywhy": a.requires_whywhy}


def point_data(db: Session, p: ReviewPoint) -> dict:
    return {"id": p.id, "sequence_no": p.sequence_no, "category": p.category,
            "discussion_point": p.discussion_point, "action_required": p.action_required,
            "action": action_data(db, db.get(Action, p.action_id) if p.action_id else None)}


@router.get("/active")
def get_active_review(review_date: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.scalar(select(ReviewSession).where(ReviewSession.review_date == review_date, ReviewSession.ended_at.is_(None))
                    .order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc()).limit(1))
    return serialize_review(row) if row else None


@router.get("")
def list_reviews(participant: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(ReviewSession)
    if participant:
        stmt = stmt.where(ReviewSession.participants.ilike(f"%{participant.strip()}%"))
    rows = db.scalars(stmt.order_by(ReviewSession.review_date.desc(), ReviewSession.id.desc()).limit(200)).all()
    return [serialize_review(x, db) for x in rows]


@router.get("/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(ReviewSession, review_id)
    if not row:
        raise HTTPException(404, "Review session not found")
    return serialize_review(row)


@router.patch("/{review_id}/reopen")
def reopen_review(review_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(ReviewSession, review_id)
    if not row:
        raise HTTPException(404, "Review session not found")
    other = db.scalar(select(ReviewSession).where(ReviewSession.review_date == row.review_date, ReviewSession.ended_at.is_(None), ReviewSession.id != row.id).limit(1))
    if other:
        raise HTTPException(409, f"Review #{other.id} is already active for {row.review_date}")
    row.ended_at = None
    db.commit()
    db.refresh(row)
    return serialize_review(row)


@router.post("")
def start_review(payload: ReviewStart, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    existing = db.scalar(select(ReviewSession).where(ReviewSession.review_date == payload.review_date, ReviewSession.ended_at.is_(None))
                         .order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc()).limit(1))
    if existing:
        result = serialize_review(existing); result["existing"] = True; return result
    row = ReviewSession(review_date=payload.review_date, started_at=datetime.utcnow(),
                        participants=payload.participants, comments=payload.comments)
    db.add(row); db.commit(); db.refresh(row)
    result = serialize_review(row); result["existing"] = False; return result


@router.patch("/{review_id}/close")
def close_review(review_id: int, payload: ReviewClose, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(ReviewSession, review_id)
    if not row: raise HTTPException(404, "Review session not found")
    if row.ended_at is None: row.ended_at = datetime.utcnow()
    if payload.comments is not None: row.comments = payload.comments
    db.commit(); db.refresh(row); return serialize_review(row)


@router.post("/{review_id}/points")
def add_point(review_id: int, payload: ReviewPointCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = db.get(ReviewSession, review_id)
    if not review: raise HTTPException(404, "Review session not found")
    if review.ended_at is not None: raise HTTPException(409, "Closed meetings cannot be edited")
    action = None
    if payload.action_required:
        if not (payload.action_description or "").strip():
            raise HTTPException(422, "Action description is required when Action Required is Yes")
        count = db.query(Action).count() + 1
        action = Action(action_no=f"ACT-{review.review_date.year}-{count:05d}", reference_date=review.review_date,
                        problem_category=payload.category or "Daily Review", problem_description=payload.discussion_point.strip(),
                        action_description=payload.action_description.strip(), owner_id=payload.owner_id,
                        due_at=payload.due_at, priority=payload.priority, action_type="DAILY_REVIEW", requires_whywhy=False)
        db.add(action); db.flush()
        db.add(ActionHistory(action_id=action.id, changed_by_id=user.id, new_status=action.status,
                             comment=f"Created from Daily Review #{review.id}; simple follow-up action"))
        db.add(ReviewActionLink(review_session_id=review.id, action_id=action.id))
    seq = (db.scalar(select(func.max(ReviewPoint.sequence_no)).where(ReviewPoint.review_session_id == review.id)) or 0) + 1
    point = ReviewPoint(review_session_id=review.id, sequence_no=seq, category=payload.category,
                        discussion_point=payload.discussion_point.strip(), action_required=payload.action_required,
                        action_id=action.id if action else None, created_by_id=user.id)
    db.add(point); db.commit(); db.refresh(point)
    return point_data(db, point)


@router.post("/actions/{action_id}/escalate-whywhy")
def escalate_whywhy(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    action = db.get(Action, action_id)
    if not action: raise HTTPException(404, "Action not found")
    if not action.requires_whywhy:
        action.requires_whywhy = True
        action.action_type = "WHY_WHY"
        if not db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == action.id)):
            db.add(ActionWhyWhy(action_id=action.id, containment_action=action.action_description, updated_by_id=user.id))
        db.add(ActionHistory(action_id=action.id, changed_by_id=user.id, old_status=action.status,
                             new_status=action.status, comment="Escalated from Daily Review to Why-Why"))
        db.commit()
    return {"id": action.id, "requires_whywhy": True}


@router.get("/{review_id}/mom")
def meeting_mom(review_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    review = db.get(ReviewSession, review_id)
    if not review: raise HTTPException(404, "Review session not found")
    points = db.scalars(select(ReviewPoint).where(ReviewPoint.review_session_id == review.id).order_by(ReviewPoint.sequence_no)).all()
    current_action_ids = {p.action_id for p in points if p.action_id}
    pending = db.scalars(select(Action).where(Action.action_type == "DAILY_REVIEW", Action.status != ActionStatus.CLOSED)
                         .order_by(Action.due_at, Action.reference_date)).all()
    pending = [action_data(db, a) for a in pending if a.id not in current_action_ids]
    return {"meeting": serialize_review(review), "mom_no": f"MOM-{review.review_date.isoformat()}-{review.id:03d}",
            "points": [point_data(db, p) for p in points], "previous_pending_actions": pending}


def _mom_rows(db: Session, review: ReviewSession):
    points = db.scalars(select(ReviewPoint).where(ReviewPoint.review_session_id == review.id).order_by(ReviewPoint.sequence_no)).all()
    rows=[]
    for p in points:
        a=db.get(Action,p.action_id) if p.action_id else None; ad=action_data(db,a)
        rows.append([p.sequence_no,p.category or "",p.discussion_point,(ad or {}).get("description",""),
                     (ad or {}).get("owner",""), str((ad or {}).get("due_at","") or "")[:10],
                     (ad or {}).get("priority",""),(ad or {}).get("status","")])
    return rows


@router.get("/{review_id}/pdf")
def download_mom_pdf(review_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    review=db.get(ReviewSession,review_id)
    if not review: raise HTTPException(404,"Review session not found")
    mom_no=f"MOM-{review.review_date.isoformat()}-{review.id:03d}"
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=10*mm,leftMargin=10*mm,topMargin=10*mm,bottomMargin=10*mm)
    styles=getSampleStyleSheet(); story=[Paragraph("Daily Review - Minutes of Meeting",styles["Title"]),
      Paragraph(f"<b>MOM:</b> {mom_no} &nbsp;&nbsp; <b>Date:</b> {review.review_date} &nbsp;&nbsp; <b>Participants:</b> {review.participants or '-'}",styles["BodyText"]),Spacer(1,5*mm)]
    data=[["Sr.","Category","Discussion / MOM Point","Action Required","Owner","Target","Priority","Status"]]+_mom_rows(db,review)
    table=Table(data,colWidths=[10*mm,25*mm,65*mm,65*mm,35*mm,25*mm,22*mm,25*mm],repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1f4e78")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
      ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP"),
      ("GRID",(0,0),(-1,-1),0.4,colors.grey),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f4f7fa")])]))
    story.append(table)
    if review.comments: story += [Spacer(1,4*mm),Paragraph(f"<b>Meeting remarks:</b> {review.comments}",styles["BodyText"])]
    doc.build(story)
    return Response(buf.getvalue(),media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{mom_no}.pdf"'})


@router.get("/{review_id}/xlsx")
def download_mom_xlsx(review_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    review=db.get(ReviewSession,review_id)
    if not review: raise HTTPException(404,"Review session not found")
    mom_no=f"MOM-{review.review_date.isoformat()}-{review.id:03d}"
    wb=Workbook(); ws=wb.active; ws.title="MOM"
    ws.append(["Daily Review - Minutes of Meeting"]); ws.append(["MOM No",mom_no]); ws.append(["Date",review.review_date.isoformat()])
    ws.append(["Participants",review.participants or ""]); ws.append([])
    headers=["Sr.","Category","Discussion / MOM Point","Action Required","Owner","Target Date","Priority","Status"]; ws.append(headers)
    for row in _mom_rows(db,review): ws.append(row)
    for cell in ws[6]:
        cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="1F4E78"); cell.alignment=Alignment(wrap_text=True)
    widths=[8,20,45,45,25,15,14,16]
    for i,w in enumerate(widths,1): ws.column_dimensions[chr(64+i)].width=w
    ws.freeze_panes="A7"; ws.auto_filter.ref=f"A6:H{ws.max_row}"
    out=BytesIO(); wb.save(out)
    return Response(out.getvalue(),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":f'attachment; filename="{mom_no}.xlsx"'})
