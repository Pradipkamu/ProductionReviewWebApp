# OEE Refinement — Phase 2

## Goal
Deliver a consistent OEE workflow across the web application, backend and Android companion app using shared authenticated APIs and server-side business rules.

## Web application
- The existing Machine / OEE page supports controlled machine-shift entry, existing-record correction, loss classification, loss reconciliation, OEE action creation, machine ranking, period trend and loss Pareto.
- The web correction workflow sends `X-Change-Reason` for both machine-shift and loss-event updates.
- Existing management filters and summary are served by `GET /oee/management-summary`.

## Backend / server
- Machine entry resolves effective-dated ideal cycle time from the master; client-supplied zero means resolve from master.
- Product, route operation, machine mapping, effective dates, quantity bounds and downtime bounds are validated by the API.
- Loss capture validates active loss categories and selected product/operation/machine context.
- Corrections require a reason of at least five characters in `X-Change-Reason`.
- Machine-shift and loss-event corrections create `GovernanceAudit` records containing actor, entity, month, reason, and before/after snapshots.
- OEE aggregation counts machine shift time once per machine/date/shift while output and ideal production time remain additive across product rows.

## Android
- Live OEE summary with date, shift, product, operation and machine scope.
- Machine-shift production entry and controlled correction with mandatory reason.
- Classified machine-loss capture and linked standard Why-Why action creation.
- Period management summary with overall OEE, A/P/Q, machine ranking, top loss categories and daily trend.
- Cycle-time master is treated as seconds per piece; no cavity or pieces-per-cycle conversion is applied without verified business definition.

## Remaining validation gates
1. Backend tests for audited corrections, reason enforcement, duplicate protection, loss classification and action linking.
2. Android compilation and runtime validation against a non-production API.
3. Web/mobile parity checks with representative records.
4. Explicit operational definition and test cases for shared fixtures, simultaneous mixed-part production and sequential product runs.

## Release safety
- Development remains on `feature/oee-refinement-web-android` and PR #51.
- No production deployment, migration or merge to `main` until CI and operational validation pass.
