Production / Process / Sales / Action WebApp v0.2.12
Quality PPM Trend update

Changes
- Adds Monthly PPM Trend beside Monthly Rejection Qty Trend on Quality / Rejection.
- Monthly PPM uses the same historical + daily monthly roll-up already provided by the backend.
- Historical PPM therefore uses uploaded Dispatch Qty when available, otherwise the MIS-history Dispatch/Actual denominator introduced in v0.2.11.
- Months with rejection but no valid denominator are not plotted as zero; they remain Pending and are counted below the chart.
- Existing Daily PPM Trend is retained and is shown when daily PPM data exists.
- Data labels remain ON by default.

Database
- No schema change.
- No data migration.
- Safe update-in-place over v0.2.11.

Install
1. Run backup_database_windows.bat.
2. Run docker compose down (do not use -v).
3. Extract this ZIP over the existing application folder and replace files.
4. Run start_windows.bat.
5. Press Ctrl+F5 once in the browser.
