# Production Review WebApp — Engineering Roadmap after v0.2.16

## P0 — Production hardening
1. Replace in-app compatibility SQL with Alembic migrations and a schema-version table.
2. Add first-login password change, password reset, strong SECRET_KEY validation, and remove usable default credentials from production mode.
3. Enforce role permissions on write/close/reopen/import APIs, not only expose a role field.
4. Add month close/reopen/correction authorization with immutable audit history.
5. Make frontend installs reproducible with package-lock.json + npm ci; keep dependency overrides only as temporary safeguards.
6. Add backup restore verification and a one-click health/diagnostics page covering DB, backend, frontend, storage, and build/version.

## P1 — Data quality and operational control
1. Add import preview/staging with row-level Accepted/Updated/Rejected reasons before commit.
2. Add master-data validation dashboard for missing route, cycle time, machine map, yield, lead time, price, weight, and plant/type/customer mappings.
3. Add explicit historical-data reconciliation reports: MIS vs rejection denominator, source totals vs phenomenon totals, and duplicate/conflict review.
4. Add transaction-derived WIP ledger (opening + inflow - outflow) instead of summary-only WIP.
5. Add partial vendor receipts as child transactions with expected-return/aging SLA.
6. Add action escalation: overdue reminders, repeated issue detection, effectiveness follow-up date, and recurrence after closure.

## P1 — Reporting / UX
1. Build a common filter state component so multi-select scope is consistent across all report pages.
2. Add saved report views and reset-to-default filters.
3. Add drill-through from compliance/rejection/OEE chart points to the exact MIS/rejection/action records for that day/product.
4. Add management exception dashboard: low compliance, high PPM, OEE loss, overdue vendor WIP, overdue actions, schedule risk.
5. Add server-side XLSX/PDF report packs in addition to CSV/print.
6. Add chart export and consistent data-label collision handling.

## P2 — Integration / scale
1. AFMS/MQTT ingestion for automatic production, cycle, downtime, and loss events with idempotent event IDs.
2. ERP/API imports for schedule, dispatch, vendor movement, and product master.
3. Power BI read-only reporting views/materialized views with documented star schema.
4. Capacity-constrained finite scheduling using route/machine/cycle-time calendars.
5. Background job queue for large imports/report generation and scheduled summaries.
6. Centralized structured logging, error IDs, metrics, and automated DB/application backup retention.
