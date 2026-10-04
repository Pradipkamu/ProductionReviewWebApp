from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PAGE = landscape(A4)
MARGIN = 10 * mm
COLORS = {
    "header": colors.HexColor("#1f4e78"),
    "subheader": colors.HexColor("#d9eaf7"),
    "label": colors.HexColor("#eef3f7"),
    "border": colors.HexColor("#7a8793"),
    "light": colors.HexColor("#f7f9fb"),
}


def _safe(value) -> str:
    if value in (None, ""):
        return "-"
    return escape(str(value)).replace("\n", "<br/>")


def _fmt_date(value) -> str:
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d-%b-%Y")
    return _safe(value)


def _fmt_dt(value) -> str:
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d-%b-%Y %H:%M")
    return _safe(value)


def build_action_plan_pdf(
    *,
    action: dict,
    plan: dict,
    contexts: list[dict],
    owner_name: str | None,
    updated_by_name: str | None,
    attachments: list[dict],
) -> bytes:
    """Render one standard, printable Why-Why action plan in A4 landscape."""
    out = BytesIO()
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ActionBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        spaceAfter=0,
    )
    small = ParagraphStyle(
        "ActionSmall",
        parent=body,
        fontSize=7,
        leading=8.5,
    )
    title = ParagraphStyle(
        "ActionTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=17,
        alignment=TA_CENTER,
        textColor=colors.white,
        spaceAfter=0,
    )
    section = ParagraphStyle(
        "ActionSection",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#17365d"),
    )

    def p(value, style=body):
        return Paragraph(_safe(value), style)

    def section_table(heading: str, rows: list[list], widths: list[float] | None = None):
        data = [[Paragraph(escape(heading), section)]]
        data.extend(rows)
        table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), COLORS["subheader"]),
            ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
            ("INNERGRID", (0, 1), (-1, -1), 0.35, COLORS["border"]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        table.setStyle(TableStyle(style))
        return table

    def label_value(label: str, value, span: int = 1):
        return [p(label, small), p(value, body)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["border"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 8 * mm, PAGE[0] - MARGIN, 8 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#56616a"))
        canvas.drawString(MARGIN, 4.8 * mm, "Production Review Manager - Controlled Why-Why Action Plan")
        canvas.drawCentredString(PAGE[0] / 2, 4.8 * mm, f"Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}")
        canvas.drawRightString(PAGE[0] - MARGIN, 4.8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        out,
        pagesize=PAGE,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=13 * mm,
        title=f"{action.get('action_no', 'Action')} Why-Why Action Plan",
        author="Production Review Manager",
        subject="Standard Why-Why Action Plan",
    )

    story = []
    heading = Table(
        [[Paragraph("STANDARD WHY-WHY ACTION PLAN", title)]],
        colWidths=[PAGE[0] - 2 * MARGIN],
    )
    heading.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLORS["header"]),
        ("BOX", (0, 0), (-1, -1), 0.8, COLORS["header"]),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([heading, Spacer(1, 4 * mm)])

    meta = [
        [p("Action No.", small), p(action.get("action_no")), p("Reference Date", small), p(_fmt_date(action.get("reference_date"))), p("Category", small), p(action.get("problem_category"))],
        [p("Priority", small), p(action.get("priority")), p("Status", small), p(action.get("status")), p("Due Date", small), p(_fmt_dt(action.get("due_at")))],
        [p("Owner", small), p(owner_name), p("Closure Date", small), p(_fmt_dt(action.get("closed_at"))), p("Plan Updated By", small), p(updated_by_name)],
    ]
    meta_table = Table(meta, colWidths=[23*mm, 45*mm, 28*mm, 42*mm, 25*mm, 89*mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), COLORS["label"]),
        ("BACKGROUND", (2, 0), (2, -1), COLORS["label"]),
        ("BACKGROUND", (4, 0), (4, -1), COLORS["label"]),
        ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([meta_table, Spacer(1, 3 * mm)])

    context_rows = [[p("Plant", small), p("Product", small), p("Operation / Stage", small), p("Machine", small), p("Context Date", small)]]
    if contexts:
        for c in contexts:
            context_rows.append([
                p(c.get("plant")),
                p(c.get("product")),
                p(c.get("operation") or "Product level"),
                p(c.get("machine") or (f"Machine #{c.get('machine_id')}" if c.get("machine_id") else "-")),
                p(_fmt_date(c.get("date"))),
            ])
    else:
        context_rows.append([p("-"), p("-"), p("-"), p("-"), p("-")])
    ctx_table = Table(context_rows, colWidths=[35*mm, 63*mm, 72*mm, 48*mm, 35*mm], repeatRows=1)
    ctx_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLORS["label"]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([ctx_table, Spacer(1, 3 * mm)])

    story.append(section_table("1. PROBLEM DEFINITION & IMMEDIATE CONTAINMENT", [
        [p("Problem Description", small), p(action.get("problem_description"))],
        [p("Immediate / Proposed Action", small), p(action.get("action_description"))],
        [p("Containment / Immediate Action", small), p(plan.get("containment_action"))],
    ], [50*mm, 203*mm]))
    story.append(Spacer(1, 3 * mm))

    why_rows = [[p("Why Level", small), p("Cause / Explanation", small)]]
    for n in range(1, 6):
        why_rows.append([p(f"Why {n}", small), p(plan.get(f"why{n}"))])
    why_table = Table(why_rows, colWidths=[35*mm, 218*mm], repeatRows=1)
    why_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLORS["label"]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([Paragraph("2. WHY-WHY ANALYSIS", section), why_table, Spacer(1, 3 * mm)])

    story.append(section_table("3. ROOT CAUSE & COUNTERMEASURES", [
        [p("Root Cause", small), p(plan.get("root_cause"))],
        [p("Corrective Action", small), p(plan.get("corrective_action"))],
        [p("Preventive / Systemic Action", small), p(plan.get("preventive_action"))],
    ], [50*mm, 203*mm]))
    story.append(Spacer(1, 3 * mm))

    story.append(section_table("4. VERIFICATION & EFFECTIVENESS", [
        [p("Verification Method", small), p(plan.get("verification_method"))],
        [p("Verification Result", small), p(plan.get("verification_result"))],
        [p("Effectiveness Check Date", small), p(_fmt_date(plan.get("effectiveness_check_date")))],
        [p("Effectiveness Result", small), p(plan.get("effectiveness_result"))],
        [p("Lessons Learned / Horizontal Deployment", small), p(plan.get("lessons_learned"))],
        [p("Closure Remark", small), p(action.get("closure_remark"))],
    ], [50*mm, 203*mm]))
    story.append(Spacer(1, 3 * mm))

    evidence_rows = [[p("Evidence / Attachment", small), p("Caption", small), p("Size", small)]]
    if attachments:
        for a in attachments:
            evidence_rows.append([
                p(a.get("file_name")),
                p(a.get("caption")),
                p(f"{max(1, round((a.get('size_bytes') or 0)/1024))} KB"),
            ])
    else:
        evidence_rows.append([p("No attachment recorded"), p("-"), p("-")])
    evidence = Table(evidence_rows, colWidths=[95*mm, 130*mm, 28*mm], repeatRows=1)
    evidence.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLORS["label"]),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([Paragraph("5. EVIDENCE", section), evidence, Spacer(1, 4 * mm)])

    signoff = Table([
        [p("Prepared / Action Owner", small), p(owner_name), p("Reviewed By", small), p("________________________"), p("Approved By", small), p("________________________")],
        [p("Date", small), p(_fmt_date(action.get("reference_date"))), p("Date", small), p("________________________"), p("Date", small), p("________________________")],
    ], colWidths=[30*mm, 55*mm, 25*mm, 58*mm, 25*mm, 60*mm])
    signoff.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), COLORS["label"]),
        ("BACKGROUND", (2, 0), (2, -1), COLORS["label"]),
        ("BACKGROUND", (4, 0), (4, -1), COLORS["label"]),
        ("BOX", (0, 0), (-1, -1), 0.6, COLORS["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(signoff)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
