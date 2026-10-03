# v0.5.2 — Horizontal Monthly PPM Quantities

This patch makes the machine-filtered Monthly PPM information easier to compare across months on the **Quality / Rejection** page.

## Quality display change

- The separate vertical **Monthly PPM Detail** table is removed.
- A horizontal month matrix is embedded in the **Monthly PPM Trend** panel, immediately below the graph.
- The matrix contains exactly two quantity rows: **Rejection Qty** and **Dispatch Qty**.
- PPM remains visible as labels on the graph and is not duplicated as a third table row.
- Long date ranges scroll horizontally while the quantity label column remains visible.
- Machine, process, product, plant, phenomenon and shift filters continue to control both the graph and its quantity matrix.
- Months with rejected quantity but no denominator continue to show **Pending** instead of an incorrect zero, and are not plotted as zero PPM.

## Safe update

This release contains no database migration. Use the supplied update-in-place script so the existing PostgreSQL database is backed up and verified before application replacement. Keep `.env` and `database/` intact. Never run `docker compose down -v`.
