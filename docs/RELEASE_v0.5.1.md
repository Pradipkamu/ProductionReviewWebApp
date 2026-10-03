# v0.5.1 — Machine PM, Utilities and Costing Master

This release adds a dedicated **Machine Master** page without replacing the effective-dated part/operator/capacity controls introduced in v0.5.0.

## Machine master data

- Stable machine code and name
- Machine type, plant/shop, department and cost center
- Manufacturer, model, serial/asset number and commissioning date
- Last PM completed date and PM frequency in days; next PM is calculated automatically
- Default manpower required with three-decimal precision, allowing values such as `0.5`
- Rated power in kW and expected running load factor
- Compressed-air consumption in CFM
- Active/inactive status, remarks and mandatory change reason

The default machine manpower is a reference and costing default. Capacity planning continues to use the effective-dated operator requirement for the selected part, operation and machine, because one machine can require different attendance for different setups.

## Cost inputs and formulas

- Labor cost/hour = `operators × labor rate/operator-hour`
- Power cost/hour = `rated kW × load factor × electricity rate/kWh`
- Air cost/hour = `CFM × 60 ÷ 1,000 × compressed-air rate/1,000 cubic feet`
- Hourly conversion cost = labor + power + air + maintenance + consumables + depreciation + other overhead
- Estimated conversion cost/piece = `hourly conversion cost × planning cycle seconds/piece ÷ 3,600`
- Planned run cost = `allocated quantity × estimated conversion cost/piece`

The Capacity / Manpower page uses its effective operator requirement and planning cycle time when calculating the part-specific estimate. Saved allocation revisions retain hourly and per-piece cost snapshots. These values are planning estimates, not accounting postings.

## History and safe update

Each create or edit writes a complete Machine Master snapshot with reason, user and timestamp. Migration `0008_machine_master_costing` only adds nullable machine fields, allocation cost snapshots and a history table. Existing machines, production, OEE, schedules and database volumes are preserved.

Use the supplied update-in-place script so PostgreSQL is backed up and verified before migration. Keep `.env` and `database/` intact. Never run `docker compose down -v`.
