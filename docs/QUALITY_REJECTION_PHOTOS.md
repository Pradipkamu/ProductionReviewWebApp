# Daily Quality Rejection Photographs

Daily rejection records support up to five protected defect photographs.

## API

- `POST /api/quality/daily/{rejection_id}/attachments` — multipart upload using the `file` field and optional `caption`.
- `GET /api/quality/daily/{rejection_id}/attachments` — authenticated metadata listing.
- `GET /api/quality/daily/{rejection_id}/attachments/{attachment_id}` — authenticated image download/preview.

## Validation and storage

- Maximum five photographs per rejection.
- JPG, JPEG, PNG and WEBP only.
- Maximum 8 MB per image.
- File signatures are validated; extensions and client MIME declarations are not trusted.
- Files are stored below the configured `ATTACHMENTS_DIR/quality-rejections/{rejection_id}/` path with generated storage names and restrictive file permissions.
- SHA-256 is stored and checked before download. Duplicate content on the same rejection is idempotently returned.
- The database stores metadata and a relative storage path; image bytes are not stored in PostgreSQL.

## Web experience

The Daily Rejection Detail table displays a `Photos (n/5)` control when a record has images. The secure gallery loads image bytes through the authenticated API, shows thumbnails and a larger selected image, and offers download. Object URLs are revoked when the gallery closes.

The Android companion source is included in `mobile-android/`. Its rejection form captures up to five photos, uploads them only after the rejection record has been saved, and uses these same endpoints. Existing rejection calculations and historical Excel import flows are unchanged.

## Deployment

Run the normal Alembic migration to revision `0022_rejection_photos`. Ensure the configured attachments directory is on persistent storage and included in the application's backup/restore plan. Do not expose the directory as a public static web path.
