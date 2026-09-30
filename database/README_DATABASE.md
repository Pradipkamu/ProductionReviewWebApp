# Persistent Database & Application Data

This entire `database/` folder is intentionally separate from the application source.

- `postgres/` — live PostgreSQL database files (PostgreSQL creates its `pgdata/` subfolder here). **Do not delete or overwrite this folder during an app update.**
- `backups/` — SQL backups created by `backup_database_windows.bat` / `backup_database_linux.sh`.
- `imports/` — Excel files uploaded through the web application.
- `attachments/` — reserved for action evidence, photos, PDFs and other future attachments.

## Safe application update

1. Run `backup_database_windows.bat`.
2. Run `docker compose down` (never add `-v`).
3. Replace only `backend/`, `frontend/`, `docs/`, scripts and compose files from the new release.
4. Keep this `database/` folder unchanged.
5. Run `start_windows.bat`.

The backend performs compatible schema additions automatically at startup. Major future migrations will be supplied as versioned migration scripts.
