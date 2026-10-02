# v0.4.5 — Daily Production Control and early warnings

## Daily operating sequence

The home page is now a single daily control point:

1. **Check schedule readiness** — shows customer plan and stage-plan coverage.
2. **Upload once** — Admin and Planning users can preview and confirm the combined daily-production workbook without leaving the page.
3. **Act on exceptions** — prioritized warnings link directly to schedules, process monitoring, actions, vendor WIP or data quality.

The upload status distinguishes a missing record from an uploaded value of zero. A missing record is a data blocker. A reported zero is a critical production result and remains visible as such.

## Early warnings

- customer plan exists but the effective process flow or stage plan is missing;
- customer MIS/dispatch or a planned stage actual has not been uploaded;
- zero or low dispatch and stage output against a positive plan;
- a daily rejection has no PPM denominator, or calculated daily PPM is high;
- effective sales price is missing;
- action due date or vendor expected-return date is overdue.

The next-seven-day plan count provides a short readiness horizon. Filters for Plant, Product Group, Customer and Product apply to both the control steps and warning list.

## PPM correction

Historical and daily quality aggregation no longer marks PPM pending merely because a zero-rejection row has no denominator. A missing denominator still blocks PPM whenever that row contains a positive rejection quantity. This prevents false pending months while preserving denominator integrity.

## Safer update startup

Both update-in-place scripts now run `docker compose up -d db` and wait for PostgreSQL readiness before the verified pre-update backup. This removes the earlier `service "db" is not running` failure when the Compose database container was stopped or had not yet been created for the current folder. Existing `.env` and `database/` data remain in place. Never run `docker compose down -v`.

This release includes the v0.4.4 GitHub changes that use the parent `Disp_Done` Stage Schedule as the customer schedule source and show that source and revision history on the Schedule page.

No database schema migration is required for v0.4.5.
