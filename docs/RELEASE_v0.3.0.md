# v0.3.0: P0 and P1 continuation

Baseline verified from `ProductionReviewWebApp_v0.2.16_GitHubReady(1).zip`. `VERSION.txt` said 0.2.16; frontend package said 0.2.15 and backend API said 0.2.8. Repository was empty before this task; the supplied source is now preserved as a separate baseline commit.

## P0

Implemented additive Alembic migrations, forced initial password change, strong secret validation/setup, password change/admin reset, token invalidation, API role enforcement, reasoned month close/reopen/correction authorization and transactional audit evidence. Frontend builds use committed lockfile and `npm ci`. Patched frontend tooling/router dependencies are pinned. Update scripts verify a PostgreSQL backup before starting the new backend.

## P1

- Data quality includes missing route, positive cycle time, internal-operation machine mapping, effective price, weight, customer/plant/type, historical/daily PPM denominator, unresolved imports, overlapping effective ranges, quality conflicts and duplicate requirements.
- Preview/confirmation covers current production, historical MIS, historical prices, daily rejection and monthly rejection imports. New/Updated/Unchanged/Rejected counts cover primary business rows; additional supporting master/process counts are included in detailed stats. Historical normalized imports collect row errors before simulation; quality importers collect their row errors. Other importer parser exceptions reject the workbook with their available diagnostic. Any error prevents confirmation; valid rows are not partially committed. Preview expires after 30 minutes and must be repeated if relevant business/master data changes. Temporary previews expire after one day and are removed during a later preview request.
- Daily/weekly/monthly compliance charts open MIS/requirements/actions details for the selected period and scope. PPM charts open daily/monthly phenomenon records with resolved denominators. Machine OEE details include shift production and loss records/charts. Chart labels stay on by default; weekly compliance stays at the last 8 weeks; new review scopes use existing multi-select filters.
- Exceptions use configurable thresholds for compliance, PPM, OEE and major loss, plus overdue WIP/actions, missing-route schedule risks and data quality. Schedule risk is a missing-route signal, not a full finite-capacity production forecast.
- In-app reminders refresh automatically each minute while the backend is running; one reminder per action/kind/day. Overdue age escalates to Management at 7 days and Admin at 14 days. Effectiveness checks use the existing Why-Why effectiveness date/result. Repeated descriptions/categories are probable recurrence signals, explicitly requiring review. No external email/WhatsApp notification is sent.
- Vendor receipts are appended with reference-based idempotency. Partial receipts add to received totals and reject quantity is a subset of received quantity. Negative, over-pending, backdated-before-outward and conflicting duplicate receipts are rejected. Receipts cannot be edited/deleted via API; legacy totals become an opening entry. Pending/aging/expected-return reporting remains compatible.

## Deferred P2

AFMS/MQTT integration and Power BI reporting/star-schema layer remain documented only.

## Validation and limits

See `BUILD_VALIDATION_v0.3.0.txt` for actual completed checks. No live production database was available here; no production backup or update has been executed. The safe update must be run on the actual installation. GitHub CI passed against PostgreSQL 16: 34 tests passed and the original optional workbook test was skipped. Frontend clean install/build/audit also passed. See BUILD_VALIDATION_v0.3.0.txt for the tested source commit and workflow URL. Existing optional workbook fixture test may remain skipped when its external workbook is absent.
