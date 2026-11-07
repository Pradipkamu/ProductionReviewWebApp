# OEE Refinement — Phase 2

## Goal
Extend the Phase 1 live Android OEE dashboard into a practical shop-floor workflow while keeping web and Android on the same authenticated API and business rules.

## Phase 2A — mobile operational capture
- Add Android machine-shift production entry using the existing `POST /oee/machine-entry` endpoint.
- Resolve ideal cycle time from the effective-dated master on the server; Android sends zero as the sentinel and does not perform cycle-time conversion.
- Add Android loss-category lookup from `GET /masters/loss-categories`.
- Add classified machine-loss capture using `POST /oee/loss-events`.
- Allow an operator to raise a standard OEE Why-Why action from a newly captured loss using `POST /oee/loss-events/{id}/raise-action`.
- Keep duplicate-entry protection and count/time validation on the server.

## Existing server-side controls reused
- Product, route operation, machine mapping and effective-date validation.
- Effective cycle-time master lookup.
- Good/reject/total count validation and downtime bounds.
- Active loss-category validation.
- Action context and standard Why-Why plan creation.

## Remaining Phase 2 work
1. Add mobile correction workflows with mandatory reason and a reliable audit trail. Do not bypass or weaken server correction controls.
2. Add mobile OEE management period view: trend, machine ranking, target gap and loss Pareto, using `GET /oee/management-summary`.
3. Add server/API and Android tests for machine entry, loss classification, duplicate handling, action linking, and role-based access.
4. Verify operational data cases for multi-product shifts, shared fixtures, simultaneous mixed-part production and sequential product runs before any calculation changes.
5. Validate web/mobile parity and representative records before release.

## Release safety
- Development stays on `feature/oee-refinement-web-android` and PR #51.
- No production deployment, migration, or merge to `main` is part of this phase until validation is complete.
