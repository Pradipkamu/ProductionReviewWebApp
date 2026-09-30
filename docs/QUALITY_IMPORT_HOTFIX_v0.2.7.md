# v0.2.7 Quality Import Hotfix

Fixes historical Quality/Rejection import failures caused by duplicate or colliding phenomenon codes in the same workbook when SQLAlchemy SessionLocal uses `autoflush=False`.

Examples handled safely:
- `DAMAGE` and `Damage` -> one master phenomenon.
- `OD -` and `OD (-) (+)` -> distinct phenomena with unique generated codes (`OD`, `OD_2`).

The failed v0.2.6 import transaction is rolled back, so the same historical rejection workbook can be uploaded again after applying this patch.

## Install
1. Run `backup_database_windows.bat`.
2. Run `docker compose down` (do not add `-v`).
3. Extract this ZIP over the existing application folder and replace files.
4. Run `start_windows.bat`.
5. Re-upload the same historical rejection workbook.
