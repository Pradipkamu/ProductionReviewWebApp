v0.2.5 - One-time Historical Daily MIS Import

Purpose:
- Adds a dedicated one-time historical Daily MIS importer for the normalized Historical_Daily_MIS_Import sheet.
- Does not alter database schema.
- Existing September 2026 data is untouched unless the uploaded file explicitly contains the same Date + Product key.
- Historical Daily Requirements are stored as frozen baseline/revised plan.
- Product names must already exist in Product Master; unknown names are rejected to avoid duplicate masters.
- Exact duplicate files are skipped by the existing import batch SHA-256 protection.

Install:
1. Run backup_database_windows.bat.
2. docker compose down
3. Extract this ZIP over the current application folder and replace files.
4. start_windows.bat
5. Open Excel Import -> One-time Historical Daily MIS.
6. Upload Historical_Daily_MIS_May-Aug_2026_WebApp_Import.xlsx.

Note on sales values:
The importer uses effective-dated Web App Sales Price history. If there is no price effective for May-Aug, quantity history imports correctly but sales values remain 0 until a historical Sales Price Revision is entered. The price revision engine will then recalculate affected MIS sales.
