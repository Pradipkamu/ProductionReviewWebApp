# OEE Refinement — Phase 1

## Scope

This branch refines the existing OEE calculation path and connects the Android OEE screen to authenticated production data. It does not change production deployment or rewrite historical records.

## Audit findings

1. The web application already has controlled machine/product/operation/shift entry, effective-dated cycle-time lookup, loss classification, downtime reconciliation, OEE actions, management trends and loss Pareto.
2. The Android app had an OEE navigation item, but its screen was a placeholder and did not call the OEE APIs.
3. OEE summaries aggregated machine-shift duration by summing every product row. If multiple products were recorded for the same machine/date/shift, the same shift duration, planned break and downtime could be counted more than once.
4. Cycle-time master rows include `cavities` and `pieces_per_cycle`, while OEE currently consumes `ideal_cycle_time_sec` directly. The business meaning and unit of this master value must be confirmed against actual shop-floor standards before applying any conversion; do not assume that cavities and pieces-per-cycle are interchangeable.
5. Android currently implements live read-only OEE summary viewing. Machine shift entry, loss entry, correction audit, and management-period charts remain future mobile work.

## Phase 1 changes

- Added a shared OEE aggregation helper that groups machine time by machine/date/shift.
- For repeated product rows in one machine shift, shift duration, planned break and downtime are counted once (maximum recorded value per shift group); product quantities and ideal production time remain additive.
- Distinct machines and distinct shifts remain additive.
- Applied the helper to daily machine summaries and management-period aggregation, including daily trend and machine comparisons.
- Added unit tests for multiple products sharing one machine shift and for distinct shifts.
- Replaced the Android OEE placeholder with a live, authenticated dashboard using:
  - product, date and shift selection;
  - effective route/operation and mapped machine lookup;
  - live OEE, Availability, Performance and Quality;
  - planned production/run time and downtime-loss reconciliation indicators;
  - a diagnostic warning when unclassified or over-classified downtime exists.
- Added Android compilation to GitHub Actions so Kotlin/Compose changes are checked alongside backend and frontend builds.

## Calculation policy retained

- Availability = run time / planned production time.
- Performance raw = ideal production time / run time.
- Reported Performance is capped at 100%; raw Performance remains visible for diagnosis.
- Quality = good quantity / total quantity.
- Reported OEE = Availability × capped Performance × Quality.
- Only Availability-category loss minutes reconcile against machine downtime. Performance and Quality loss events remain separately classified.

## Safety and data preservation

- No migration is introduced in Phase 1.
- No production database or attachment files are changed by this branch.
- Existing manual entries, cycle-time history, action links and correction audit requirements are retained.
- The shared-time aggregation is a reporting correction; it does not rewrite individual product rows.

## Next audit / development gates

1. Confirm the exact unit and meaning of ideal cycle time, cavities and pieces per cycle from the actual machine/part master and shop-floor sheets.
2. Define how shared fixtures, simultaneous multi-part production and sequential product runs are recorded so ideal production time and machine availability are not conflated.
3. Add a data-quality warning when records for the same machine/date/shift contain conflicting shift duration, break or downtime values.
4. Extend Android with controlled shift entry and loss capture, followed by correction reasons and action creation, using the same API validations as web.
5. Add Android management trend and loss Pareto after the operational capture workflow is stable.
6. Validate with representative historical machine-shift data before considering a production rollout.
