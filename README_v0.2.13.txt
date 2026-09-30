Production / Process / Sales / Action WebApp v0.2.13
Quality chart layout update

Changes
- Monthly Rejection Qty Trend remains first.
- Monthly PPM Trend is now plotted directly below Monthly Rejection Qty Trend instead of beside it.
- Both monthly charts use full available page width for clearer labels.
- Existing Daily PPM Trend remains below the monthly charts.
- No calculation, API, database, or historical-data change.

Install
1. Run backup_database_windows.bat.
2. Run docker compose down (do not use -v).
3. Extract this ZIP over the existing application folder and replace files.
4. Run start_windows.bat.
5. Press Ctrl+F5 once in the browser.
