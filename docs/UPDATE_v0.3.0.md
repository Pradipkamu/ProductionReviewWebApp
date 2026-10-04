# Safe update from v0.2.16

1. Keep a copy of the current application source/package. Preserve the existing `.env` and the entire `database/` directory. Keep PostgreSQL on its existing bind mount; do not change Compose project name or database path during this upgrade.
2. Copy the complete new backend, frontend, scripts and documentation into the same application directory. Do not combine selected files from different releases. Do not replace `.env` with `.env.example` and do not delete database files. The new source ZIP contains no PostgreSQL data or secrets.
3. On Windows run `update_in_place_windows.bat`. On Linux run `./update_in_place_linux.sh`. The updater builds the images and verifies the new backend's authentication/API import contract before it stops the running application. It then starts the existing `db` service and waits until PostgreSQL is ready. A failed build or import preflight exits before stopping the application. After preflight, the scripts stop backend/frontend, export a custom-format dump, check it with `pg_restore --list`, and retain a SHA-256 alongside it. If backup validation fails, the backend remains stopped and no migration is started.
4. Alembic runs under a PostgreSQL advisory transaction lock on backend startup. The baseline adopts existing tables, adds known older compatibility columns if required, verifies required columns and fails on unrecognized missing columns. Subsequent revisions add password governance, audits, correction grants, vendor receipt ledger, reminders, versioned process definitions and stage allocation history. Unknown column/type/constraint differences require manual review; the baseline does not claim full compatibility with arbitrary schemas.
5. Verify http://localhost:8000/api/health and inspect `docker compose logs backend`. Sign in and change the initial password. Check MIS totals, price history, rejection/PPM and pending vendor quantities against the previous version. Imported legacy vendor cumulative receipts are retained as `LEGACY-OPENING` ledger entries.

Do not use `docker compose down -v`. Do not erase `database/postgres` or automatically restore over a live business database.

## Recovery

If migration or health validation fails, retain the dump and logs, stop application writes and review the failure. PostgreSQL migrations are executed in a transaction; a failed transaction should roll back schema/data changes, but check the actual database before restarting old code. Keep an unchanged pre-update source copy. Validate the dump by restoring into a separate scratch PostgreSQL database before selecting a recovery path. Successful v0.3.0 upgrades are additive; do not use a destructive Alembic downgrade to remove audit or receipt history.

The scripts assume the existing Compose database service/user/database are `db`, `pms`, `pms`, as in v0.2.16. Adjust the dump commands before use if the installation differs. If another application writes to this PostgreSQL database, stop its writes as well during the backup/update window.

## Secret handling

Launch/update scripts generate a random persistent secret only for missing or placeholder values. Existing configured secrets and credentials are preserved. Weak non-placeholder secrets cause backend startup to fail rather than silently rotate the key. Set a new random secret explicitly in `.env` if needed; this invalidates existing sessions. `ENVIRONMENT=production` requires a configured persistent key. Direct development without `.env` uses a process-local random key; sessions then expire on process restart.
