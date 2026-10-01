# v0.4.2 — Shop Production Capture

This release connects image capture to the application. The standalone HTML design is no longer needed for this workflow.

## Update your existing installation

1. Copy the update package contents into `D:\Machine Shop MIS`, replacing application files. Keep `.env` and the entire `database` folder.
2. Start Docker Desktop. From PowerShell in that folder, run `docker compose up -d db` if the database is stopped.
3. Run `update_in_place_windows.bat`. The script builds the images, verifies database readiness, stops application writers, creates and verifies a PostgreSQL dump in `database/backups`, then starts the updated application. The first build downloads Tesseract and its English data; internet is needed for the build. OCR runs locally afterward.
4. Confirm the script reports success, refresh the application, and open **Shop Production Capture**. Startup applies additive Alembic migration `0005_shop_capture`. No existing production tables or quantities are rewritten.

Do not replace `.env`, delete the database folder, or use `docker compose down -v`. Retain source-image files in `database/imports/shop-capture` alongside database backups: a PostgreSQL dump does not include uploaded image files. This package is intended for the v0.4.1 installation; use the full source package if earlier application files are missing.

## Daily use

1. Upload one or several PNG/JPG/WebP screenshots. Each image becomes its own saved report; return to reports through the saved-report list. Limits: 15 MB and 16 megapixels per image.
2. Review the source image against OCR text. Correct transcription if needed and click Extract / re-extract figures. Choose the correct Target:Actual or Actual/Target interpretation for that shop. Changing transcription or pair order resets row extraction.
3. Confirm plant, shop, date and canonical shift A/B/C. Plant comes from product masters. If a machine has a department, the shop must match it. Shop identification is reviewer-confirmed in this release; automatic shop recognition and reusable alias profiles are not yet implemented.
4. Keep stock, dispatch, quality totals, rework, operator assignments and incomplete machine rows pending. Select **Fresh machine production → OEE** only for a verified fresh machine count. Choose product, effective operation and machine; enter total/good counts, shift/break/downtime minutes and the effective ideal cycle seconds per piece. Add a row reason confirming the source meaning.
5. Enter a review reason and Save review. Validate saved review. Errors identify missing mappings, cycle master mismatch, invalid quantities/times, existing machine shifts and closed-month restrictions.
6. Confirm machine import. Only selected, validated machine rows enter Machine / OEE. Remaining observations stay in a partial report and may be reviewed later. Imported rows and report identity become immutable; the receipt identifies created entries. Complete machine rows must all pass validation together.

For a closed month, use the existing Historical correction controls with an authorized correction number. Saving or previewing a capture does not consume it; successful business import does. Existing machine shifts are never overwritten by this workflow.

## Scope and limits

- Local English printed-text OCR using Tesseract. No external OCR account or API key; no automatic WhatsApp access. Photographs, blur, unusual layouts and spelling can affect recognition. Always review the image.
- Conservative parsing of the three supplied report styles, original OCR retained, editable transcription, explicit blank quantities and pair ambiguities, source-line evidence, mixed-product/rework warnings.
- Saved per-image drafts, revision conflict checks, reasoned correction history, owner/admin access, Admin/Production writes, file-content duplicate detection, business duplicate checks and atomic imports.
- Complete **single-product machine-shift production/OEE** imports. Mixed-product totals stay pending because duplicating shift time per product would distort OEE. Product-run time allocation is future work.
- Stock/WIP, dispatch, standalone quality/rework totals and loss remarks remain review observations. They do not post to MIS, stage actuals, vendor transactions or loss events in this release. Continue the existing combined Excel daily upload for MIS and stage actuals.
- No automatic downtime estimation or inferred rejection categories. OEE is not calculated for incomplete drafts. Cycle time must match the effective master.
- One ready row per machine/date/shift. If that shift already exists, resolve it through the existing application workflow; this importer will not add a second competing record.
- Pending report rows can be completed and imported later. An imported report retains source and review history. Re-importing an identical image reopens the saved report.

Future work: approved shop profiles and alias learning; mixed-product run allocations; explicit stock, quality, loss and dispatch posting contracts. AFMS/MQTT and Power BI remain deferred P2 items.

## Validation

Automated checks cover real local OCR on a generated clear report image, supplied text-pattern parsing, duplicate uploads and machine shifts, import replay, incomplete/invalid OEE fields, stale drafts, partial import immutability, role/owner protection, closed months and additive migration preservation. The frontend production build is checked. OCR accuracy on actual plant photos still requires review during use.

Tesseract command reference: https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html
