# ProductionReviewWebApp v0.5.1

React + TypeScript · FastAPI · PostgreSQL · Docker Compose · Nginx

This release continues the supplied v0.2.16 source with P0 database/security/governance controls and P1 review workflows. Source and business data remain separate.

## Existing installation

Read [Safe update](docs/UPDATE_v0.3.0.md). Copy application files over the existing application folder while keeping `.env` and `database/` intact. Run `update_in_place_windows.bat` on Windows or `./update_in_place_linux.sh` on Linux. These scripts build first, stop application writers, verify a PostgreSQL backup, and then start the new backend/frontend against the same database mount. Never run `docker compose down -v`.

## Fresh installation

Use `start_windows.bat` or `./start_linux.sh`. The launcher generates a persistent random `SECRET_KEY` when the environment contains a placeholder. Configure the initial `ADMIN_PASSWORD` privately in `.env`; the default temporary login is `admin` / `ChangeMe123!`. The first login must change its password before application access. Existing users must also change passwords after the first migration.

Application: http://localhost:5173 · API: http://localhost:8000/docs

## Approved process flows

The corrected process design is implemented with 23 product definitions and 151 active stages. Use [Process flow setup](docs/RELEASE_v0.4.0.md) after the safe application update. The approved Excel template is included at `backend/templates/Production_Process_Upload_v0.4.0.xlsx` and available from Excel Import Preview. Definitions and stage allocations use their setup previews. Normal daily uploads use one **Daily Production Upload** preview and confirmation for customer plans/dispatch and stage actuals together. See [v0.4.1 daily workflow](docs/RELEASE_v0.4.1.md). Existing database facts remain intact.

## Release features

- Alembic adoption of legacy databases and additive schema revisions; no startup `create_all()` for upgrades.
- Strong secret validation, initial password change, password change/reset, token invalidation and API roles.
- Month Close/Reopen, one-use correction authorization and before/after audit evidence.
- Committed frontend lockfile, pinned direct dependencies and `npm ci` in Docker.
- Data Quality / Management Exception dashboards, configurable thresholds, charts and detailed records.
- Excel preview and confirmation, row errors, duplicate detection, and stale-preview rejection.
- Compliance and PPM chart drill-down; machine production/loss drill-down with OEE charts.
- In-app daily overdue reminders/escalation, effectiveness due checks and probable recurrence detection.
- Append-only vendor receipt transactions, partial receipts, duplicate reference protection, pending quantity and aging.

Historical schedules imported with zero or incorrect plans can now be explicitly corrected from their effective date with preview, reason and audit evidence. Original imported plans and actual dispatch quantities are preserved. See [May schedule correction](docs/RELEASE_v0.3.1.md).

See [Release notes](docs/RELEASE_v0.3.0.md), [API roles](docs/SECURITY_AND_GOVERNANCE.md) and [roadmap](docs/ROADMAP_v0.2.16.md). AFMS/MQTT and Power BI reporting/star schema remain P2 and are not implemented.

## Development and tests

Backend: `pip install -r backend/requirements.txt -r backend/requirements-dev.txt`, then `cd backend && PYTHONPATH=.:tests python -m pytest -q`.
Frontend: `cd frontend && npm ci && npm run build`. Use Node 22.12+.
Migrations: `cd backend && python -m app.migrate` or `alembic upgrade head` with configured `DATABASE_URL`.

Tests default to a disposable SQLite file. CI also uses isolated PostgreSQL test databases. Never direct tests at business data.

## v0.4.3 — OCR feature reverted

Shop Production Capture has been removed from the application. Existing daily Excel/MIS workflows remain. Capture schema and evidence are retained for safe updates from v0.4.2. OCR remains removed; controlled manual OEE capture resumes in v0.4.7. See [safe revert instructions](docs/RELEASE_v0.4.3.md).

## v0.4.5 — Daily Production Control

Built on the v0.4.4 parent `Disp_Done` schedule unification, the home page now guides the daily review through three steps: schedule readiness, one combined production upload, and early-warning action. Missing uploads remain distinct from reported zero production. Warnings cover missing process/stage plans, low dispatch or stage output, high PPM or missing denominator, overdue actions, and overdue vendor receipts. Each warning opens the relevant work page. The updater now starts and waits for PostgreSQL automatically before it creates its verified backup. See [release notes](docs/RELEASE_v0.4.5.md).

## v0.4.6 — Controlled Daily Rejection Template

The Quality page now creates a fresh Daily Rejection workbook from the current Product, Process, Machine and Phenomenon masters. Required master fields use reliable named-range dropdowns, Product-dependent Plant/Customer/Type fields are protected, and Preview independently rejects missing or invalid fixed data. Formula-filled unused rows are ignored. See [release notes](docs/RELEASE_v0.4.6.md).

## v0.4.7 — Controlled OEE and Loss Actions

Machine / OEE now uses one controlled record per date, shift, product, operation and machine. Effective master cycle time and mapped machines drive entry, duplicate rows are blocked, corrections require a reason, Availability losses reconcile separately to downtime, and both low OEE and individual losses can open standard Why-Why actions. Management reports now include machine-shift and loss-event detail with action status. The Data Quality dashboard flags duplicate entries, unclassified output/downtime and over-classified losses. Excel OEE import/helper work remains intentionally pending until the actual machine-shop forms are supplied. See [release notes](docs/RELEASE_v0.4.7.md) and [OEE workflow/audit](docs/OEE_WORKFLOW_AND_AUDIT_v0.4.7.md).

## v0.4.8 — Restore Verification and System Diagnostics

System Diagnostics now checks the loaded frontend/backend versions, database connection and schema revision, persistent imports/attachments/backups storage, disk capacity and latest backup status. The Windows and Linux restore-verification scripts restore a selected dump into a temporary isolated database, verify core tables, and remove the temporary database without modifying the live `pms` database. See [release notes](docs/RELEASE_v0.4.8.md).

## v0.5.0 — Machine Capacity and Manpower Planning

Capacity / Manpower Planning combines the monthly operation schedule with effective machine mapping, cycle time, operator requirement, plant calendar and machine capacity settings. It calculates available pieces, machine hours, capacity load, shortages and average/rounded operator needs; planners can auto-allocate or revise part-to-machine quantities without overwriting issued revisions. Cycle time, operator requirement, mapping and capacity changes retain effective-dated history and reasons. See [release notes](docs/RELEASE_v0.5.0.md).

## v0.5.1 — Machine PM, Utilities and Costing Master

The dedicated Machine Master captures fractional default manpower, last PM date/frequency, rated power, expected power load, compressed-air consumption and transparent labor/utility/maintenance/consumable/depreciation/overhead cost rates. It calculates hourly conversion cost, feeds part cycle-time cost estimates into Capacity / Manpower, and retains reasoned machine-master history. See [release notes](docs/RELEASE_v0.5.1.md).
