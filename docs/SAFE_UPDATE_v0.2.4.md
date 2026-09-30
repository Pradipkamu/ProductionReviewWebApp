# Safe update to v0.2.4

Use the **Update-in-Place** package for an existing v0.2.2 or v0.2.3 installation.

1. Run `backup_database_windows.bat`.
2. Run `docker compose down` (do **not** use `-v`).
3. Extract the Update-in-Place ZIP over the application folder and replace files.
4. Do not delete or replace `database/` or `.env`.
5. Run `start_windows.bat`.

v0.2.4 adds new tables only (`quality_*`, plus the v0.2.3 Why-Why/attachment tables if not already present). `Base.metadata.create_all()` creates missing tables on startup. Existing Product/MIS/Schedule/Action rows are not dropped or rewritten.

A compatibility test was run from a v0.2.2 SQLite schema to v0.2.4: existing Product and Action rows survived and all new tables were created.

The Full package is intended for a fresh installation. It is not required for an existing system.
