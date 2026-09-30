# Production, Process, Sales & Action Management System — v0.2.16 Consolidated

Web application for Daily MIS, changing customer schedules, operation monitoring, vendor WIP, actions, machines/OEE/losses and management reporting.

> **Current consolidated source:** v0.2.16. See `RELEASE_v0.2.16.md` for the latest release summary and `docs/ROADMAP_v0.2.16.md` for recommended next engineering work.

## Technology
- Frontend: React + TypeScript + Vite
- Backend: Python + FastAPI + SQLAlchemy
- Database: PostgreSQL
- Deployment: Docker Compose

## Start on Windows
1. Install and start Docker Desktop.
2. Extract this release to a permanent folder, e.g. `D:\ProductionReview`.
3. Double-click `start_windows.bat`.
4. Open `http://localhost:5173`.

Default development login:
- User: `admin`
- Password: `ChangeMe123!`

Change the password / `.env` settings before shared deployment.

## Persistent data — important
All persistent application data is under one folder:

`database/`

- `postgres/` — live DB
- `backups/` — SQL backups
- `imports/` — uploaded workbooks
- `attachments/` — reserved for action documents/photos

This means future application releases can replace the code without replacing the database. Read `docs/UPDATE_GUIDE.md`.

## Excel import
The importer reads the `PBI_Products` master by **header name**, not fixed column position. The current workbook fields are supported including:
- Product
- Customer
- Type (stored as reporting Type / Product Group)
- Plant
- Sales Price
- Finish Weight

Duplicate protection:
- exact same workbook uploaded twice → second import is skipped by SHA-256 file hash
- same Date + Product with same values → unchanged
- same Date + Product with changed values → existing record is updated, not duplicated
- new dates/products → inserted
- absence from a newer workbook never automatically deletes database history

The latest supplied workbook `Daily Production review(3).xlsx` is included as `sample_data/Daily Production review.xlsx`.

## Reports
### Compliance Reports
Daily / Weekly / Monthly, single part and all parts, with Plant → Customer → Type/Group → Part filters.
Metrics: Quantity, Sales ₹, Tonnage MT.

### Management Reports
- Operation daily / weekly / monthly compliance
- Process funnel and WIP
- Vendor compliance, pending WIP, on-time return and aging
- OEE / Availability / Performance / Quality trends
- Loss Pareto and machine loss hours
- Action closure compliance, owner aging and recurring problem Pareto
- Schedule revision impact
- Month-end projection and recovery requirement

See `docs/REPORTS.md` for the complete list.

## Database backup
Double-click:

`backup_database_windows.bat`

Backups are written to `database/backups/`.

## Useful URLs
- Web app: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/health`

## v0.2.1 review/action fix

- Daily Review no longer trusts a stale browser-only review ID.
- Active review is synchronized from PostgreSQL for the selected date.
- Close Review shows errors instead of failing silently and is idempotent.
- Start Review reuses an already-active session for the same date.
- Added **Raise action** directly on Daily Review and on each priority exception.
- Actions raised on an active review date are automatically linked to that review and remain open after the review is closed.
- Actions page can be prefilled from Daily Review and shows the linked review number.

## v0.2.2 — Sales Price Revision & Calendar Control

- Added effective-dated **Sales Price Revision** in `Schedule / Price / Calendar`.
- Price history preserves old prices and applies the new price only from the selected effective date.
- Existing MIS sales rows on/after the effective date are recalculated automatically.
- Re-importing Excel no longer overwrites an approved effective-dated price revision.
- Working Calendar now renders every date even when no explicit database row exists.
- Default calendar rule remains **Monday-Saturday working / Sunday off**.
- Added bulk actions: **Set Sundays Off**, **Mark Range Off**, **Mark Range Working**.
- Holiday/off-day name and reason are captured.
- Added calendar change history/audit trail by Plant and month.
- Calendar remains Plant-specific; schedule recalculation uses each product's Plant calendar.


## v0.2.3 — Standard Why-Why Action Plan

Every action raised anywhere in the web app now uses one common Why-Why workflow. The quick action header remains lightweight, then the same structured plan is completed for Production, Quality, OEE/Loss, Vendor, Schedule and other review actions.

Standard plan: Immediate containment → Why 1..Why 5 → Root Cause → Corrective Action → Preventive/Systemic Action → Verification → Effectiveness → Lessons Learned / Horizontal Deployment. Why 3..5 are optional when root cause is already demonstrated. Closure is blocked until the core Why-Why, verification and effectiveness fields are completed.

Action evidence can be uploaded and stored under the persistent `database/attachments/` folder. PostgreSQL stores attachment metadata and the file path/hash; application upgrades do not replace the evidence folder.


## v0.2.4 — Quality / Rejection Management

- Added dedicated Quality / Rejection module.
- Standard daily rejection Excel template can be downloaded from the web app using current Product / Plant / Process / Machine / Phenomenon masters.
- Daily rejection import is idempotent by business key and exact-file SHA-256 protection.
- Historical normalized rejection workbook import is supported for the prepared BAL / TVSM / HMCL history.
- PPM denominator rule: final `Disp_Done` rejection uses Daily MIS Disp Done actual; intermediate operation/machine rejection uses same-stage production where available.
- Quality Phenomenon Master prevents accidental duplicate defect names. Unknown typed phenomena are rejected by import rather than auto-created.
- Quality dashboard includes date/plant/product/process/machine/shift/phenomenon filters, PPM trend, component Pareto, phenomenon Pareto and detailed rows.
- Rejection rows can raise the existing Standard Why-Why action and remain linked to the quality record.
- Historical aggregate/breakdown scope is retained so HMCL Total and Plant 2050 breakdown are not double-counted.
- Data labels are rendered by default on common bar/line/trend charts.


## v0.2.5 — One-time Historical Daily MIS

- Added dedicated import for the normalized `Historical_Daily_MIS_Import` sheet.
- Imports/updates by Date + Product without deleting dates that are not in the file.
- Creates frozen baseline Daily Requirements for historical days.
- Uses the effective-dated Sales Price History already loaded in the database, so historical Plan Sales / Actual Sales follow the correct price for each date.
- Exact repeat files are skipped by SHA-256; changed files update the existing business key instead of duplicating it.

## v0.2.6 — Fresh-start Historical Sales Price Import

- Added one-time `Historical_Sales_Price_Import` Excel upload.
- Supports multiple revisions for the same product in the same month.
- `Effective To` is derived automatically from the next revision; users only enter `Effective From`.
- Product names must match the Product Master; unknown names are rejected rather than silently creating duplicate products.
- Preserves Revision Reference, Reason and Source Document for audit.
- Re-importing a changed workbook updates Product + Effective From; exact-repeat files are skipped.
- Existing Daily MIS sales on/after a price revision are recalculated automatically.

### Recommended fresh-start import order

1. Start the application and verify Product Master.
2. Import the current/refined Product Master / production workbook if required.
3. Import **Historical Sales Price** revisions.
4. Import **Historical Daily MIS**.
5. Import historical rejection data.
6. Start normal daily MIS / Quality operation.

Templates are provided in `sample_data/import_templates/`.
