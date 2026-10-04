# v0.5.5 — Security & Governance Phase 2

This release hardens uploads, secrets, database credentials and backup/restore evidence without forcing HTTPS. Oracle HTTP compatibility from v0.5.4 remains unchanged.

## Upload and attachment protection

- Excel import preview accepts only .xlsx / .xlsm.
- Uploaded workbooks must be valid Office Open XML ZIP packages containing the expected workbook structure.
- Upload size defaults to 32 MB.
- Expanded Office-package size defaults to 128 MB to reduce ZIP-bomb risk.
- Unsafe internal ZIP paths and corrupt Office archives are rejected before business parsing.
- Action evidence uses an extension allow-list: PDF, PNG, JPG/JPEG, WEBP, XLSX/XLSM, DOCX, PPTX, TXT and CSV.
- Executable, HTML, SVG, script and arbitrary archive uploads are rejected.
- PDF/image signatures and Office document structure are validated rather than trusting the browser MIME type.
- Stored attachment names are random UUIDs; original names are sanitized for display.
- Attachment storage paths are containment-checked before write/read.
- Evidence downloads use nosniff and private/no-store response headers.
- Accepted/rejected Action evidence uploads are recorded in the Security Event audit.

## Database and secret hardening

Fresh installations now generate a persistent application SECRET_KEY, a strong random PostgreSQL password, and a non-default bootstrap administrator password.

Existing installations are deliberately not silently rotated during update because changing only .env would disconnect an already initialized PostgreSQL database.

Windows:
    .\rotate_database_password_windows.ps1

Linux:
    chmod +x rotate_database_password_linux.sh
    ./rotate_database_password_linux.sh

The rotation changes the live PostgreSQL pms role password, updates .env, recreates the backend and verifies /api/health.

The System Diagnostics page reports credential-strength warnings without displaying secret values.

## Backup and restore readiness

Manual backup scripts now create PostgreSQL custom-format .dump backups, validate them with pg_restore --list, and add SHA-256 sidecars.

Windows:
    .\backup_database_windows.ps1

Linux:
    ./backup_database_linux.sh

Restore verification still restores only into a temporary isolated database. After a successful test it now records database/backups/restore_verification.json.

System Diagnostics displays latest backup freshness, custom/legacy format, SHA-256 verification, backup count, isolated restore verification, restored schema version, secret/network checks and active upload policy.

Default freshness policy: latest backup 48 hours; isolated restore verification 30 days.

## Oracle HTTP

Keep REQUIRE_HTTPS=false and TRUST_PROXY_HEADERS=false until HTTPS is actually working. This release does not redirect HTTP to HTTPS.

PostgreSQL and FastAPI host bindings remain localhost-only by default.

## Database migration

No new database migration is required by v0.5.5. It uses the v0.5.4 schema head 0010_security_sessions.
