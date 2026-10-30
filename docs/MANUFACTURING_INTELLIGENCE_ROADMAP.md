# Manufacturing Intelligence Roadmap

Branch: `feature/manufacturing-intelligence-roadmap`
Baseline: `dd6612d709a36740c8b1566b71e0215f48043ec3`
Target: Windows-first validation; no production deployment until explicit approval.

## Goal

Evolve ProductionReviewWebApp into an integrated manufacturing performance and operations management system. This roadmap is deliberately additive: reuse existing business rules, APIs, tables, and pages wherever possible; do not duplicate existing modules or replace trusted calculations without regression evidence.

## Guardrails

1. All work stays on this feature branch until the user validates it on Windows and approves release.
2. Do not modify `main`, production infrastructure, production `.env`, or production data.
3. Preserve historical records and effective-dated masters. Prefer additive schema changes with reversible migrations.
4. Do not invent master data, targets, thresholds, ownership hierarchies, or planning assumptions. Make them configurable and clearly label missing setup.
5. Keep AI and automated recommendations read-only initially. Any write action requires explicit user confirmation and existing authorization checks.
6. Every phase includes backend tests, frontend build/tests, migration checks against PostgreSQL, and a Windows Docker Compose test checklist.
7. Validate calculations against existing MIS, dispatch, rejection, schedule, capacity, OEE and MOM source records before presenting consolidated KPIs.

## Existing capabilities discovered at baseline

The repository already has dedicated dashboard, analytics, insights, reports, advanced reports, capacity planning, machine master, quality, OEE, vendor, actions and daily meeting pages. Backend routers/services already include dashboard, analytics, insights, reports, capacity, OEE, quality, vendor, actions and reviews. Migration history is at `0018_mom_owner_collaboration`.

Existing implementation status documents schedule revision/compliance reporting, vendor WIP and aging, machine capacity and monthly allocation, OEE/loss capture, quality rejection/PPM, action follow-up/Why-Why, and diagnostic/backup workflows. Therefore the work below focuses on integration, usability, data quality, predictive signals and missing workflow links rather than rebuilding these capabilities.

## Ten workstreams

### 1. Executive Control Tower
- Audit current dashboard and analytics APIs before adding endpoints.
- Build plant-wide and cross-plant KPI overview: production plan/actual, dispatch plan/actual, sales, rejection/PPM, OEE/loss, vendor WIP and overdue actions.
- Reuse existing filters (date/month, plant, customer, product group, product); show data freshness and denominator/coverage.
- Add drill-through from every KPI to the authoritative detail page and selected filters.
- Do not silently combine incompatible date bases or denominators.

### 2. Dispatch vs Actual Intelligence
- Consolidate daily schedule requirements, actual dispatch, cumulative gap and schedule revisions into a part-wise timeline/matrix.
- Link relevant MOM blockers/actions and production availability.
- Add configurable risk rules with explainable reasons; no invented promise dates or automatic schedule changes.
- Reconcile totals against existing MIS and compliance reports.

### 3. Machine Capacity & Production Planning Intelligence
- Extend existing capacity and monthly allocation rather than replace it.
- Surface machine/part compatibility, monthly load, shortage, available hours, cycle-time/operator history and fixture/mixed-part assumptions where master data supports them.
- Flag missing or stale master data and distinguish estimated from confirmed capacity.
- Any allocation approval remains an explicit authorized action with revision snapshots.

### 4. MOM Action Intelligence
- Build part-wise issue/action timeline across MOM, quality, production loss and dispatch risks.
- Add aging, overdue and repeat-issue views using existing action history and ownership.
- Integrate escalation only with configured ownership and notification rules.
- Preserve current MOM owner/participant controls and action closure requirements.

### 5. Quality Intelligence
- Enhance existing rejection/PPM analytics with recurring phenomenon, part/process trends, Why-Why linkage and effectiveness follow-up.
- Show denominator source and data completeness for each PPM result.
- Do not change established PPM formulas without reconciliation tests and explicit release notes.

### 6. Vendor Performance
- Extend existing vendor WIP/receipt/aging workflows with supplier scorecards, overdue trends, rejection and delivery compliance where source data exists.
- Clearly distinguish unavailable supplier commitments from late receipts.
- Avoid fabricated lead times or supplier ratings.

### 7. Production Forecasting
- Add transparent run-rate and month-end projection using existing working calendars, schedule revisions and actuals.
- Show assumptions, remaining working days, recovery/day and confidence/coverage limitations.
- Keep forecasts advisory; do not write back to schedules.

### 8. Automated Alerts
- Introduce configurable alert rules for dispatch risk, overdue actions, quality spikes, capacity shortage and vendor aging.
- Start with in-app notifications/digest and a notification log; external email/WhatsApp delivery is a separate opt-in integration.
- Add deduplication, quiet periods, delivery status and recipient authorization.

### 9. Document & Historical Knowledge
- Index authorized MOM/action attachments and structured notes for metadata and text search where extraction is supported.
- Provide source links, access checks and retention-aware indexing.
- Do not expose attachment contents across users who lack permission; no external AI upload by default.

### 10. AI Management Assistant
- Start read-only with grounded queries over authorized application APIs.
- Answers must cite records, dates, filters and calculation definitions; state when data is missing.
- No direct database writes, action closure, schedule changes or master edits through AI.
- Add audit logging and permission-aware retrieval before enabling broadly.

## Delivery sequence

| Increment | Workstreams | Exit criteria |
|---|---|---|
| 0. Audit & data contracts | All | KPI dictionary, page/API map, dependency and regression inventory approved |
| 1. Management visibility | 1, 2, 5 | Reconciled dashboard and dispatch/quality drill-through |
| 2. Planning intelligence | 3, 7 | Explainable capacity and forecast views with master-data warnings |
| 3. Operational control | 4, 6, 8 | Action/vendor visibility and configurable, auditable alerts |
| 4. Knowledge & AI | 9, 10 | Permission-tested document search and read-only grounded assistant |

The ten workstreams are a product scope, not a promise to ship them in one unreviewed commit. Each increment will be committed separately on this branch for Windows testing.

## Windows validation contract

From PowerShell, in the user's existing working copy:

```powershell
git fetch origin
git switch feature/manufacturing-intelligence-roadmap
git pull --ff-only origin feature/manufacturing-intelligence-roadmap
git status --short
docker compose build
docker compose up -d
docker compose ps
```

Run the repository's backend tests and frontend build/test commands for each increment. Use a separate Windows test database and test uploads; never point the Windows test environment at production data for writes. Capture screenshots and report any discrepancy before continuing to the next increment.

## Definition of done

- Existing workflows and calculations remain regression-tested.
- New screens have plant/date/product filters consistent with the application.
- Every KPI is traceable to source records and documented formulas.
- API authorization and page access are enforced server-side.
- PostgreSQL migrations are tested and do not destroy historical data.
- Windows Docker Compose build and manual acceptance tests pass.
- No change is deployed to Pradipweb until the user explicitly approves it.
