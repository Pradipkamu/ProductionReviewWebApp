Production / Process / Sales / Action WebApp v0.2.10
Historical Quality Visibility Fix

PURPOSE
- Historical rejection quantities now appear in the Quality dashboard, monthly trend and Pareto reports even when Dispatch Done quantity is not yet loaded.
- Dispatch Done quantity is required only for calculated historical PPM.
- Adds 'Show Imported History' shortcut and historical monthly detail table.
- Prevents double counting: if daily quality exists for the same product/month, the daily roll-up is used instead of monthly historical data.
- Historical monthly data is excluded while Shift / Process / Machine filters are active because those old monthly records do not contain dependable granularity for those fields.

INSTALL
1. Run backup_database_windows.bat
2. Run: docker compose down
3. Extract this ZIP over the current v0.2.9 installation and Replace existing files.
4. Run start_windows.bat
5. In browser press Ctrl+F5 once.

NO DATABASE SCHEMA CHANGE.
DO NOT delete the database folder and DO NOT use docker compose down -v.

EXPECTED QUALITY BEHAVIOR
- Rejected Qty / Component Pareto / Phenomenon Pareto / Monthly Reject Trend: visible without Dispatch Done Qty.
- Calculated historical PPM: shows Pending until Dispatch Done Qty is supplied.
- The historical import already reads Monthly_Dispatch_Qty_Input -> Dispatch_Qty_INPUT when present.

VALIDATION
- Backend regression: 17 passed, 1 skipped.
- Added regression test proving historical rejection is visible with dispatch_qty = NULL and PPM remains Pending.
- Quality.tsx syntax transpilation check passed.
