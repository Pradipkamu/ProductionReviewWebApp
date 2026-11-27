# Gauge lifecycle and QR tracking

## Lifecycle states

The gauge register supports ACTIVE, DUE, OVERDUE, OUT_FOR_CALIBRATION, OOT, QUARANTINED, PENDING_APPROVAL and RETIRED. Legacy calibration states PENDING, IN_CALIBRATION, CALIBRATED and FAILED remain valid so existing calibration records are not rewritten.

- ACTIVE requires a passed calibration or verification event with independent approval and a due date that has not passed.
- RETIRED is terminal. Register a replacement gauge rather than reactivating a retired record.
- Status changes require ADMIN, MANAGEMENT or QUALITY role, a reason and an audit entry.
- Issue and transfer are blocked for DUE, OVERDUE, OUT_FOR_CALIBRATION, OOT, FAILED, QUARANTINED, PENDING_APPROVAL and RETIRED. Return transactions remain allowed so blocked gauges can be returned.
- Active or calibrated gauges past their due date are presented as OVERDUE without rewriting historical events.

## QR labels

Each gauge receives an opaque UUID token. Migration 0041 backfills existing gauges and the database generates a token for new gauges. QR PNGs contain an application path and opaque token, not gauge data. Set PUBLIC_APP_URL to the externally reachable application URL (without a trailing slash) before printing labels. If it is blank, the QR contains a relative /calibration?gauge=... path and cannot be resolved independently by a phone camera until the base URL is configured. QR lookup requires sign-in.

## Safety scope

Existing calibration events, certificates, impact assessments and production history are preserved. Issue/transfer blocking is enforced at the calibration location transaction endpoint only. Global blocking in every inspection/quality workflow is intentionally not enabled until all gauge-selection integration points are mapped and tested. No production migration or deployment is included.
