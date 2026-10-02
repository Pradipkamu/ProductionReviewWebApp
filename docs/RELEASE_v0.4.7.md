# v0.4.7 — Controlled OEE and Loss Actions

## Outcome

The web OEE workflow is ready for controlled manual daily use without depending on the future Excel form. OCR remains removed. OEE Excel import and its helper function are deliberately deferred until the actual forms from all machine shops are attached and compared.

## Daily capture

- Select Date, Shift, Product and Operation; the page lists the effective mapped machines.
- The effective ideal cycle time comes from Standard Cycle Time master and is read-only on the page.
- Only one machine-shift row is accepted for the exact Date + Shift + Product + Operation + Machine scope.
- Existing rows load for correction. Updating one requires a reason and uses the existing month-close/correction-authorization controls.
- Impossible time/count combinations are rejected. Unclassified output remains visible as a warning instead of being silently treated as good output.

## Loss control and actions

- Loss entry uses the approved Loss Category dropdown and shows the OEE component.
- Only Availability loss minutes reconcile to downtime. Performance and Quality loss records remain reportable but do not consume downtime minutes.
- The page displays unclassified downtime and over-classified Availability loss immediately.
- Low OEE or an individual loss can create an action. Repeated clicks return the already-linked action.
- Every OEE action receives the standard Why-Why plan and inherits product, operation, machine, date and loss-event context.

## Reports and warnings

- Management OEE report retains OEE/A/P/Q trends, machine ranking and loss Pareto.
- It now includes the underlying machine-shift records and individual loss events, including linked action number/status.
- Machine ranking shows open and overdue action counts.
- Data Quality adds daily warnings for duplicate OEE shifts, missing cycle values, unclassified output, unclassified downtime and loss minutes exceeding entered downtime.

## Calculation policy

`Planned production time = Shift duration − Planned break`

`Run time = Planned production time − Downtime`

`Availability = Run time / Planned production time`

`Performance = (Ideal cycle seconds × Total count) / Run time seconds`

`Quality = Good count / Total count`

`Reported OEE = Availability × min(Performance, 100%) × Quality`

Raw Performance remains visible. Values above 110% are flagged because they normally indicate an incorrect effective cycle master, quantity or time entry.

## Deployment

No database migration is required. Use the update-in-place script; it keeps the existing PostgreSQL data mount and creates a verified backup before application writers start. Never use `docker compose down -v`.
