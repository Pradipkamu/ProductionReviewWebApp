# Implementation status

## Implemented in this build

- JWT login and role field
- PostgreSQL / Docker deployment
- Excel import for current Daily Production Review workbook
- Product/customer/sales price import
- Existing daily Plan/Actual import
- Existing Daily MIS operation-route inference
- Daily process actual import
- Off-day calendar import
- Opening schedule revision import
- Schedule revision preview and apply
- Effective-date remaining-working-day redistribution
- Baseline plan preservation
- Backward process requirement propagation through route yield/lead-time
- Historical MIS edit + audit log
- Process monitor + manual process entry
- Date/product/operation/machine action context
- Action follow-up / closure history
- Vendor WIP movement backend + UI
- Machine master
- Manual machine shift entry
- OEE calculation
- Loss event capture
- Downtime/loss reconciliation
- Month-over-month sales analytics
- Action reason analytics
- Review-session API
- Isolated PostgreSQL backup restore verification scripts
- One-click system diagnostics for frontend/backend version, database, storage and backup status
- Effective-dated machine mapping, standard cycle time and operator requirement history
- Effective-dated machine shift, break and planning-efficiency capacity settings
- Monthly machine capacity, load, shortage, machine-hours and operator calculations
- Revisioned monthly part-to-machine allocation with calculation snapshots
- Dedicated Machine Master with plant/shop, type, manufacturer, model, serial and cost center
- PM completed date/frequency, calculated next-PM status and overdue data-quality warning
- Fractional default machine manpower, rated power and compressed-air consumption
- Labor, energy, air, maintenance, consumables, depreciation and overhead cost model
- Hourly, per-piece and monthly planned machine conversion-cost estimates
- Horizontal two-row Rejection Qty / Dispatch Qty matrix within the Monthly PPM graph panel

## Deliberately left configurable, not guessed

- Exact standard yield by operation
- Operation lead time by product
- Initial machine-to-operation assignments
- Initial standard/ideal cycle times and pieces per cycle
- Initial operators per running machine
- Initial shifts, minutes, breaks and planning efficiency by machine
- Machine utility rates, hourly burden assumptions and PM frequency
- Vendor expected lead-time rules
- User/department ownership hierarchy
- Closed-month correction authorization matrix

These are master-data decisions and should not be invented from Excel.

## Next engineering increments already supported by the schema

- AFMS/MQTT automatic machine events
- ERP integration
- Attachments to actions
- Email / WhatsApp alerts
- Predictive month-end risk
- Finite day/shift sequencing inside the monthly machine allocation
- Power BI direct PostgreSQL model


## v0.1.3 reporting
- [x] Daily compliance charts — all parts / single part
- [x] Weekly compliance charts — all parts / single part
- [x] Monthly compliance charts — all parts / single part
- [x] Quantity / Sales ₹ toggle
- [x] Revised schedule plan used in compliance when available
- [x] Current-month part-wise compliance comparison

## v0.1.4 completed

- Plant and Product Group master dimensions
- Header-driven `PBI_Products` import
- Finish-weight / tonnage calculations
- Plant-specific working calendar usage in schedule planning
- Plant / Customer / Product Group / Product filters on core review screens
- Qty / Sales / Tonnage daily-weekly-monthly compliance reporting
- Plant / Group / Customer compliance roll-ups
- Safe warning for populated but unlabelled `PBI_Products` columns

## v0.2.0 completed
- Exact duplicate workbook detection using SHA-256 import batches
- Insert / update / unchanged counts on repeated or incremental Excel imports
- Excel `Type` mapped to Type / Product Group filter and reports
- Plant code imported as a plant reporting dimension
- Dedicated persistent `database/` tree for PostgreSQL, backups, imports and attachments
- Database backup scripts
- Operation daily / weekly / monthly compliance reporting
- Process funnel and WIP reporting
- Vendor receipt compliance, aging, overdue and monthly trend reporting
- Machine OEE / Availability / Performance / Quality trends
- Loss Pareto, machine loss-hours and monthly loss trend
- Action closure compliance, owner aging and recurring problem Pareto
- Schedule revision quantity / sales impact reporting
- Month-end run-rate projection, recovery/day and risk reporting
- CSV-for-Excel export and Print / Save PDF for management reports

## Future integrations still intentionally deferred
- AFMS/MQTT automatic cycle/loss feed
- ERP/API transactional import
- Native XLSX/PDF server-side report packs
- Finite day/shift sequencing inside the monthly machine allocation
- Predictive models beyond current run-rate forecast

### v0.2.1
- Review server-state synchronization: implemented
- Stale localStorage review recovery: implemented
- Idempotent review close: implemented
- Daily Review quick action creation: implemented
- Automatic ReviewActionLink on action creation: implemented

### v0.2.2
- Effective-dated sales price revision UI/API and price history.
- Historical sales-price preservation and future MIS sales recalculation.
- Excel re-import protection for manual price revisions.
- Full-month Plant calendar rendering with Mon-Sat/Sunday default logic.
- Bulk Sunday/off/working calendar updates.
- Calendar holiday/reason capture and audit history.


### v0.2.3
- Universal Standard Why-Why action plan for every action source.
- Why 1..Why 5, root cause, containment, corrective/preventive action, verification, effectiveness and lessons learned.
- Closure readiness/completion shown on Action Management.
- Action closure blocked until required Why-Why fields are complete.
- Persistent action attachment upload/download under `database/attachments`.
- Existing Daily Review automatic action linking retained.


### v0.2.4
- Dedicated Quality / Rejection database tables and APIs.
- Daily standard rejection Excel import with strict master validation.
- Historical normalized rejection import with phenomenon master upsert and dispatch-denominator support.
- Dynamic daily template download from live Web App masters.
- Final `Disp_Done` PPM denominator from Daily MIS actual; intermediate denominator from operation/machine production where available.
- Quality dashboard, PPM trend, product/phenomenon Pareto, filters and detailed rejection table.
- Quality rejection → Standard Why-Why Action link.
- Exact quality-file duplicate protection using SHA-256.
- Default data labels added to shared chart components.
