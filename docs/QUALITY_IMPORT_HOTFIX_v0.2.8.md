# v0.2.8 Quality Import Hotfix

Fixes a second historical Quality import issue: duplicate `Record_Key` values inside one workbook could reach PostgreSQL as two pending INSERTs because the SQLAlchemy session uses `autoflush=False`. The importer now preflights the complete `Historical_Rejection_Import` sheet and rejects duplicate business keys with a clear row-level validation message before any database rows are written.

The accompanying corrected import workbook fixes 23 duplicate HMCL Total keys. The original HMCL Total source sheet had its final Aug-2026 column header accidentally copied as Jun-2026. The corrected workbook normalizes that final column to Aug-2026 and restores the correct Jun/Aug production, inspection, reject totals, PPM audit values, and denominator input row.

## Install
1. Run `backup_database_windows.bat`.
2. Run `docker compose down` (do not add `-v`).
3. Extract this ZIP over the current application folder and replace files.
4. Run `start_windows.bat`.
5. Upload `Rejection_WebApp_Import_Ready_v3_Corrected.xlsx`, not the older v2 workbook.
