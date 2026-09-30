# Safe Application Update

The application source and persistent database are deliberately separated.

## Never replace this folder
`database/`

It contains:
- `database/postgres/` — live PostgreSQL files
- `database/backups/` — SQL backups
- `database/imports/` — imported Excel workbooks
- `database/attachments/` — future action evidence and documents

## Standard update
1. Double-click `backup_database_windows.bat`.
2. Run `docker compose down` or `stop_windows.bat`.
3. Copy the new release files over the old application **except `database/` and `.env`**.
4. Run `start_windows.bat`.
5. Confirm `http://localhost:8000/api/health` and the web application.

Do not use `docker compose down -v`.
