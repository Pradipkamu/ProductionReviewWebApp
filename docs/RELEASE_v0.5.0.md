# v0.5.0 — Machine Capacity and Manpower Planning

This release adds controlled monthly machine-side planning while preserving the existing database and daily production workflow. AFMS/MQTT integration and Power BI remain deferred P2 work.

## Planning workflow

1. Open **Capacity / Manpower** and select a product and month.
2. Complete any missing effective machine mapping, standard cycle time, operator requirement, or machine capacity setting. Every master change requires an effective date and reason.
3. Select an operation. The monthly requirement comes from the existing operation-level Daily Requirements produced by the schedule workflow.
4. Use **Auto allocate** to create a priority-based suggestion, adjust quantities if required, and save a reasoned monthly allocation revision.
5. Review capacity load, shortages, machine hours, average concurrent operators and rounded operators required. Previous allocation and master revisions remain visible in history.

Blank master data is never treated as zero. An incomplete mapping is shown as blocked until its required inputs are configured.

## Calculation rules

For each effective period within the selected month:

- Net minutes per working day = `shifts/day × (shift minutes − break minutes)`.
- Effective machine minutes = `net minutes × planning efficiency %`.
- Available pieces = `effective machine minutes ÷ planning cycle seconds × 60 × pieces/cycle`.
- Planning cycle time uses the effective Standard Cycle Time; if absent, it falls back to effective Ideal Cycle Time.
- Machine hours = `allocated pieces × planning cycle seconds ÷ pieces/cycle ÷ 3600`.
- Operator hours = `machine hours × operators per running machine`.
- Average concurrent operators = `operator hours ÷ available net machine hours`.
- Operators required = the average concurrent requirement rounded upward.
- Capacity load = `allocated pieces ÷ available pieces × 100`.

The engine evaluates effective dates day by day, so mid-month revisions to cycle time, manpower or capacity settings are reflected in the monthly totals. Plant working-calendar days are used; non-working days contribute no capacity.

## Revision and audit behavior

- Machine mappings, cycle times, operator requirements and capacity settings are effective-dated histories.
- A new master revision closes the previous open revision; it does not overwrite it.
- Monthly allocations are append-only revisions keyed by product, operation and month.
- Allocation records retain cycle-time, pieces-per-cycle, operator, capacity and available-capacity snapshots used when the revision was issued.
- All changes store the authenticated user, timestamp and reason.

## Safe update

Migration `0007_machine_capacity_planning` is additive. It creates the operator, capacity-setting and allocation history tables and adds reason/user attribution to existing machine-map and cycle-time histories. It does not delete production or schedule facts.

Use the normal update-in-place script. It builds first, stops application writers, creates and verifies a PostgreSQL backup, applies the migration, and restarts the application against the existing `database/` volume. Keep `.env` and `database/` intact. Never run `docker compose down -v`.
