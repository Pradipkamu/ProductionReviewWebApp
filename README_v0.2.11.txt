Production / Process / Sales / Action WebApp v0.2.11

Historical Quality PPM - MIS Dispatch Auto-Link

Changes
- Historical rejection Dispatch Done denominator is automatically resolved from Historical Daily MIS Actual Qty for the same Product + Month when the rejection record uses a dispatch denominator and is an aggregate/product-total row.
- Explicit Dispatch Qty in the rejection history workbook still has first priority.
- No separate Dispatch Qty upload is required when matching Historical Daily MIS is available.
- Existing already-imported historical rejection rows are resolved dynamically; no rejection re-import is required.
- Historical Quality table marks auto-derived denominators with "MIS".
- Plant/vendor detail rows excluded from overall aggregation are NOT assigned a product-total MIS denominator, preventing false PPM on detailed breakups.
- Future historical rejection imports also persist the MIS-derived denominator when available.
- No database schema change.

Validation
- Backend: 20 passed, 1 skipped.
- Frontend source updated; full npm build was not run in the artifact environment because frontend dependencies were not installed there. Docker rebuild on the user's installation will compile the frontend.

Install
1. Run backup_database_windows.bat
2. docker compose down
3. Extract this ZIP over the existing v0.2.10 installation and Replace existing files
4. Run start_windows.bat
5. Ctrl+F5 once in the browser

Do NOT use docker compose down -v.
