# v0.4.8 — Restore Verification and System Diagnostics

## P0 outcome

The remaining production-hardening item now has two controls:

- **System Diagnostics** checks the running frontend/backend build versions, authenticated database access and Alembic schema revision, persistent storage availability/capacity, and latest backup age/checksum status.
- `verify_backup_restore_windows.bat` and `verify_backup_restore_linux.sh` perform a real restore into an isolated temporary PostgreSQL database, verify the core `users` and `products` tables, and remove the temporary database afterward. The live `pms` database is never the restore target.

The normal update-in-place scripts still build first, stop application writers, create a custom-format database dump, validate its archive and SHA-256, and restart on the existing database mount. Backup names are now version-neutral (`pms_before_update_...`) so future releases do not retain stale version labels.

The quality-report denominator resolver also retains the established unfiltered rule that current Historical Daily MIS dispatch overrides a stale uploaded denominator, while preserving the newer plant-safe behavior: an explicit plant denominator wins for a plant filter, and a product-total MIS value is never reused for only one plant of a split product.

## Safe update

Preserve `.env` and the complete `database/` directory, then run `update_in_place_windows.bat` or `./update_in_place_linux.sh`. This release has no database migration. Never run `docker compose down -v`.

After update, sign in and open **System Diagnostics**. For a full independent restore check, run the platform restore-verification script; without an argument it selects the latest `.dump` in `database/backups`.
