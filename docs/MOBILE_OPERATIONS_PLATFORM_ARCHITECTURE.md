# Mobile Operations Platform Architecture

## Purpose

The Android companion is the shop-floor entry point for Production Review. It is designed as a modular application with shared authentication, attachment handling, auditability and synchronization rather than a rejection-only utility.

All implementation work remains on `productionmobile`. The production server and `main` branch are not changed by this work.

## Platform principles

- Reuse the existing FastAPI APIs, user accounts, roles, validation and PostgreSQL database.
- PostgreSQL remains the system of record; Android local storage is only for drafts and queued transfers.
- Use HTTPS only and existing bearer-session authentication.
- Keep uploaded files outside the database in protected server-side attachment storage.
- Store file metadata, hashes, uploader and business-record relationships in PostgreSQL.
- Validate file extension, file signature, size and storage path on the server.
- Preserve audit events for accepted/rejected uploads and integrity failures.
- Use additive Alembic migrations and avoid changing existing rejection calculations.

## Shared module roadmap

| Module | Planned capabilities |
| --- | --- |
| Quality | Daily rejection entry, defect photographs, inspection evidence, rejection history |
| Corrective actions | Action assignment, Why-Why updates, evidence uploads, verification and closure |
| Maintenance | Machine breakdown request, fault photographs, maintenance assignment, repair and downtime history |
| Production | OEE, machine loss, shift production and supervisor summaries |

Each module will have its own business tables and permissions. Common platform services will handle authentication, file validation/storage, camera capture, upload retry, audit metadata and user feedback. Module-specific attachment link tables preserve database foreign-key integrity.

## Defect photo implementation

- Maximum 5 photos per daily rejection.
- JPG/JPEG, PNG and WEBP accepted by the API.
- Maximum 8 MiB per image.
- Android captures to a private cache file using FileProvider; no public file URI is exposed.
- Photos upload only after the rejection API returns its committed record ID.
- If a photo upload fails, the rejection remains saved and the remaining photos can be retried without resubmitting the rejection.
- Server stores files under the configured protected attachments directory and stores metadata in `quality_rejection_attachments`.
- Download/list APIs require an authenticated session and verify the stored SHA-256 hash before returning a file.

### API routes

- `POST /api/quality/daily/{rejection_id}/attachments` — multipart photo upload.
- `GET /api/quality/daily/{rejection_id}/attachments` — list attachment metadata.
- `GET /api/quality/daily/{rejection_id}/attachments/{attachment_id}` — authenticated download.

### Database migration

Migration `0018_quality_rejection_attachments` adds the attachment metadata table and cascades attachment metadata when a rejection is deleted. Existing rejection rows are unchanged.

## Future attachment relationships

Use module-specific link tables such as:
- `quality_rejection_attachments`
- existing `action_attachments`
- future `maintenance_attachments`

All link tables should use the same server-side file-security/storage helpers and common metadata conventions. Do not put image bytes in PostgreSQL or expose physical storage paths to clients.

## Delivery sequence

1. Complete and test the rejection form.
2. Apply and verify the attachment migration in a non-production environment.
3. Test camera capture, upload, list, download, file limits and hash verification.
4. Display rejection photographs in the web quality/rejection view.
5. Implement durable encrypted/local offline drafts and an idempotent outbox before enabling automatic background retry.
6. Add mobile corrective-action workflows using existing action and Why-Why APIs.
7. Add machine maintenance and breakdown workflows.
8. Add OEE and machine-loss capture.

## Release safety

The current branch is development-only. Do not apply migration 0018 to the production database or distribute a pilot APK until backend tests, migration/backup verification, Android build verification, role checks and end-to-end photo tests pass.
