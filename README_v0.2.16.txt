Production / Process / Sales / Action Management WebApp v0.2.16
Daily Compliance Action Count update

Changes:
- Compliance API now returns day-wise action_count for Daily Compliance.
- Actions are counted once per action by Action.reference_date, restricted to actions linked to products inside the selected compliance scope.
- Current-month summary includes Actions Raised total.
- Daily Compliance page shows an Actions Raised KPI.
- New day-wise action strip highlights dates where one or more actions were initiated.
- Existing multi-select filters, 8-week compliance window, historical Quality/PPM features, and npm registry fix are retained.

No database schema change.
Install over v0.2.15 using normal Update-in-Place procedure.
