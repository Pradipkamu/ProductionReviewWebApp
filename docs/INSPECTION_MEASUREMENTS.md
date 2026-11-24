# Inspection Measurement Workflow

## Scope
This workflow records dimensional / characteristic measurements separately from Quality Rejection entry. It does not force a gauge onto rejection records that contain no measured characteristic.

## Setup
1. Open **Inspection Measurements** from the Quality & Rejection navigation group.
2. Create an inspection characteristic for a product, optionally scoped to an operation.
3. Enter the nominal value, absolute lower and upper limits, unit, and required sample count.
4. Record inspection date, product, operation, characteristic, gauge, lot/batch, machine, shift, operator and each sample reading.

## Gauge controls
- The backend revalidates the gauge at save time; frontend filtering is only a convenience.
- Gauge must be active and have status ACTIVE or CALIBRATED.
- A gauge with no next due date or with a due date earlier than the inspection date is blocked.
- DUE, OVERDUE, OUT_FOR_CALIBRATION, OOT, FAILED, QUARANTINED, PENDING_APPROVAL, RETIRED, PENDING and IN_CALIBRATION are blocked.
- Gauge identity, status, last calibration date, due date and location ID are snapshotted in the measurement record.
- Characteristic name, code, nominal value, limits and unit are snapshotted.
- Measurement records have no update/delete endpoint; original evidence is retained.

## Result calculation
Each sample passes when its measured value is within the inclusive absolute limits: lower_tolerance <= measured_value <= upper_tolerance. The inspection result is PASS only when every sample passes; otherwise it is FAIL. A FAIL is a recorded measurement result, not an automatic rejection or scrap transaction.

## Quality Rejection hand-off
A failed measurement must be reviewed by Quality. Create a Quality Rejection record through the existing Quality / Rejection workflow after confirming the phenomenon, detection process, reject quantity and disposition. This module intentionally does not create a rejection automatically because a dimensional failure alone does not establish the rejected quantity, defect phenomenon or lot disposition.

## API
- GET /calibration/inspection/characteristics
- POST /calibration/inspection/characteristics
- GET /calibration/inspection/measurements
- POST /calibration/inspection/measurements

## Pre-test acceptance checklist
1. Apply migrations through 0042_inspection_measurements on a test database.
2. Create a characteristic with valid tolerance limits and verify invalid limits are rejected.
3. Verify a characteristic is only selectable for its product and, when configured, its operation.
4. Save a sample set exactly matching the configured sample count.
5. Verify inclusive lower/upper limit values pass and values outside either limit fail.
6. Verify blocked gauge states, inactive gauges, missing due dates and due dates before the inspection date are rejected by the API.
7. Verify a gauge due on the inspection date is accepted if its status is ACTIVE or CALIBRATED.
8. Verify gauge/characteristic snapshots remain unchanged if the master is later edited.
9. Verify users outside ADMIN, MANAGEMENT, QUALITY and PRODUCTION cannot submit measurements.
10. Verify records are returned by date/product filters and sample values are ordered by sample number.

## Known boundaries
- No Control Plan Excel import or full control-plan revision/effective-date workflow yet.
- No statistical SPC charts, Cp/Cpk, automatic sampling plan selection or MSA/GRR calculations in this module.
- No dedicated QR camera scanner; the existing gauge QR deep link remains available from Calibration Management.
- Failed measurements require an explicit Quality decision; this module does not infer reject quantity or create a rejection automatically.
- The current schema snapshots the gauge and characteristic evidence, but not the full calibration certificate binary. The certificate remains attached to its calibration event.
