# v0.4.0 — Approved process flows and independent allocations

The corrected `Production_Process_Flow_Design_Review(2).xlsx` is consolidated into 23 product definitions, 235 retained stage/reference definitions and 151 active stages. The source filename and SHA-256 are recorded in `backend/app/data/approved_process_design.json`.

## Corrected mappings

| Product | Applied correction |
|---|---|
| K70, B104D, Platina | CPG Industries outward followed by vendor CNC receipt |
| Kubota | AN Pouring → AO Casting → AP To Rough Mill → AQ From Rough Mill → AR VMC → AS dispatch; Shradha Industries paired outward/receipt |
| TVS 558, 167, 370 | To Dattakrupa and From Dattakrupa paired vendor stages |
| Aluminium Head | FQ receipt → FR BT1 → FS BT2 → FT dispatch; FU–FY deferred |
| AF | GG Hone |
| ROF | GM outward to PK industries → GN vendor receipt → GO CNC → GP inspection → GU dispatch; deferred GQ removed from active dependency path |
| Grab Handle Machined | FF outward → FG receipt → FH VMC → FI inspection → FJ dispatch; FK–FN deferred |
| HMCL | Parallel supplier branches, five dispatch variants and separate HV parent dispatch; HP inactive alias of HK |
| Platina 99 | Historical-only definition; existing quality and master records retained |

Blank powder-coating vendor assignments remain pending. The system does not invent company, machine mappings, cycle times, quantities or allocations. Existing product customer/plant/type masters are preserved when a matching master already exists. A missing product creates an explicit master from the approved definition and is listed in the import preview's results.

## Update and first use

1. Preserve your existing `.env` and entire `database/` directory. Copy the full release application into the existing application directory. Run `update_in_place_windows.bat` or `./update_in_place_linux.sh`. Follow `docs/UPDATE_v0.3.0.md`. The scripts build, stop application writers, validate a PostgreSQL backup and restart the application on the same database mount.
2. Startup runs additive Alembic revision `0004_process_flows`. It adds three tables and changes no legacy business rows. Process definitions are installed through the import workflow, not silently during migration.
3. Open **Excel Import Preview** and download **Production_Process_Upload_v0.4.0.xlsx**. It is also included in `backend/templates`. The `Flow_Definition` sheet contains the approved stages. Its default effective date is **2026-10-01**. Change all rows for a product together if another effective date is intended. Enter your Company; review unresolved vendor assignments. Keep stage codes stable when renaming a stage or moving its source column.
4. Preview **Flow Definition**. Review errors, pending vendors and counts, then confirm. Each changed definition creates a new route/flow revision. A repeat of the same definition is unchanged. Existing route operations and machine mappings remain historical references; assign new machine/cycle-time mappings where Data Quality shows them pending.
5. Fill `Stage_Schedules` with product, stage code, first day of month, effective date, **monthly allocated pieces**, reference and reason. Remove unused rows. Blank is missing; numeric **0** is an intentional zero allocation. These allocations represent row 4's process/vendor schedule. They are independent of customer dispatch schedules, price/sales figures, stocks and actual production.
6. Preview **Stage Schedules**, inspect each stage's working dates and daily quantities in detailed results, then confirm. Plant working-calendar overrides apply; without an override, Sunday is off. Integer remainders go to earlier working days and preserve the exact allocation total.
7. Fill `Daily_Actuals` with stage code, date, total actual pieces and rejected pieces. Enter zero rejects explicitly where applicable. Remove unused rows. Preview **Daily Actuals**, review row errors, then confirm. The same combined workbook may be confirmed once for each of these three import kinds.
8. Open **Process Monitor**, select a product and date. The approved flow shows branch/variant filters, predecessor stages, allocations, daily plans, actuals, rejects, a labelled chart and detail table. Click a chart bar or **Enter actual** to inspect or record that stage. Missing values remain visibly missing.

## Historical protection and allocation rules

Definitions and allocation history are immutable through application writes. To change them, append a revision with its effective date and reason. Existing facts stay attached to their original route operation. The applicable flow is selected by effective date, then revision number.

A stage schedule revision subtracts **issued plans before its effective date** from its revised monthly allocation and divides the balance over remaining working days. It does not subtract actuals. Stable stage codes allow prior plans to be counted across flow revisions, using the definition applicable on each earlier date. Earlier issued plans and baseline quantities remain unchanged. Allocation snapshots retain working dates, quantities, reference and reason. Customer schedule changes cannot regenerate or overwrite these independent stage requirements.

These stage schedules do not automatically overwrite the customer dispatch schedule on the Schedule screen. Use that screen for the customer target. The supplied review sheet's Schedule Review quantities still refer to the earlier source layout; shifted Kubota/Aluminium/Grab columns make automatic quantity transfer unsafe. Current allocations must be entered explicitly.

Changing an existing actual or parent MIS dispatch requires a correction reason. Closed months require reopening or a user-bound Historical Correction grant. Preview rolls back all business writes and does not consume the grant; successful confirmation consumes it. Before/after audit evidence is retained. A failed row or stale preview prevents the entire workbook from committing.

Only the authoritative parent dispatch stage updates MIS actual quantity and actual sales. Existing MIS plan, effective price and plan sales remain intact. HMCL variant details never separately update parent MIS. Once all five details and HV are present, the details must sum exactly to HV. Partial details do not fabricate a total. Historical PPM continues to resolve its denominator from matching MIS dispatch.

Vendor outward/receipt daily figures are operational summaries. They do not fabricate challans or receipts in Vendor WIP. Use the existing outward transaction and partial-receipt ledger with an assigned active vendor outward stage. Vendor assignment and effective-date checks prevent linking the wrong vendor/stage.

After explicit flows are installed, the old inferred `PBI_Products + PBI_Fact_Daily` current-workbook importer is blocked with guidance to use stable stage-code imports. Historical MIS, price and quality imports remain available. This prevents shifted columns from silently retaining their old meanings.

## API and data design

- `process_flow_versions`: product, original route version, company, effective date, revision, definition hash, source and reason.
- `process_flow_stages`: stable code, role, branch, variant/group, vendor, predecessors, source-column provenance, inactive/alias markers and existing route-operation link.
- `stage_schedule_allocations`: append-only monthly allocations with effective dates and calendar/distribution snapshots.
- Existing `daily_requirements`, `process_daily_summary`, MIS, vendor receipt ledger, machine/cycle-time and quality entities remain linked through route-operation/product IDs.
- Imports: `/api/import/preview/process-design`, `/stage-schedules`, `/stage-daily`; commit through `/api/import/confirm`.
- Read APIs: `/api/flows/approved-design`, `/api/flows/monitor`, `/api/flows/template`.
- Admin/Planning can import definitions and schedules. Admin/Planning/Production can import daily actuals. View Only cannot mutate data.
- Data Quality adds missing company, vendor assignment and stage allocation conditions. Legacy sequential WIP arithmetic is not applied to parallel explicit flows.

The committed template can be regenerated using `scripts/build-process-template.mjs` in an environment with `@oai/artifact-tool`. Its import contract is tested using the actual committed workbook.

AFMS / MQTT and the Power BI/star-schema layer remain P2 and are not implemented.
